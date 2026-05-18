"""Собрать ``table_pattern.allow`` regex для DB recipe
из authoritative ``/db-mapping`` API 1С.

Зачем
-----

DB recipe подтягивает реальные типы колонок, PK/FK и статистики — но для тех
же URN, которые наш 1С-плагин уже эмитит как «скелет». Без явного фильтра
стандартный
``acryl-datahub[postgres]`` коннектор сканирует все таблицы в
``schema_pattern`` (для боевой 1С-базы это тысячи строк ``_Reference*``,
``_AccumRg*``, ``_Const*`` и пр., из которых нам нужны только десятки
таблиц по объектам, перечисленным в 1С recipe).

Прописывать имена в ``table_pattern.allow`` руками — хрупко: при
изменении scope в 1С-recipe нужно держать второй recipe в синхронизации,
и легко промахнуться (наш 1С-плагин транслирует имена объектов в
``_Document<id>``, ``_Reference<id>`` через метаданные конфигурации,
угадать вручную тяжело).

Решение: **источник правды — 1С-сервис**, а не DataHub search index.
Скрипт читает scope из 1С recipe (``object_filters.include_objects``),
опрашивает ``GET /db-mapping/{type}/{name}`` для тех же объектов и собирает
regex по полному имени ``<database>.<schema>.<table>`` — именно так стандартный
postgres-коннектор применяет ``table_pattern.allow``.

Использование
-------------

    python3 scripts/pg_tables_pattern.py            # → выведет regex в stdout
    python3 scripts/pg_tables_pattern.py --debug    # → ещё и список таблиц в stderr
    python3 scripts/pg_tables_pattern.py --best-effort
        # → при ошибке/пустом результате вернёт safe-default `(?!)`

Reference runner подставляет результат как env var
``POSTGRES_TABLE_PATTERN_ALLOW``, который DB recipe берёт через
``${POSTGRES_TABLE_PATTERN_ALLOW:-(?!)}``.

Опции / окружение
-----------------

* ``--database`` / ``$POSTGRES_DATABASE`` — фильтр базы (default:
  ``ONEC_INFOBASE_NAME`` или ``1c-test``).
* ``--schema``   / ``$POSTGRES_SCHEMA``   — фильтр схемы (default: ``public``).
* ``--recipe``   — путь к 1С recipe, откуда берётся scope объектов.
* ``--base-url`` / ``$ONEC_BASE_URL`` — адрес API сервиса 1С.
* ``--username`` / ``$ONEC_USERNAME`` — логин 1С.
* ``--password`` / ``$ONEC_PASSWORD`` — пароль 1С.

Поведение на ошибке или пустом результате: по умолчанию fail-fast
(``exit 1``). Для ручной диагностики есть ``--best-effort`` — тогда скрипт
печатает warning в stderr и выводит ``(?!)`` (regex, который не матчит ни
одной таблицы). Штатный reference ingest не использует best-effort: DB ingest
является authoritative источником физической схемы и не должен молча
превращаться в «0 таблиц».
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import requests
import yaml
from expandvars import expand  # type: ignore[import-untyped]

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATAHUB_DIR = _SCRIPT_DIR.parent
_SRC_DIR = _DATAHUB_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from datahub_1c.api.client import OneCApiClient  # noqa: E402
from datahub_1c.api.models import TABLE_PURPOSE_TABULAR_SECTION  # noqa: E402
from datahub_1c.config import ObjectFiltersConfig  # noqa: E402
from datahub_1c.mapping.urn import pg_normalize  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Собрать table_pattern.allow regex из /db-mapping 1С "
            "по scope текущего recipe."
        ),
    )
    parser.add_argument(
        "--recipe",
        default=os.environ.get(
            "ONEC_RECIPE",
            str(_DATAHUB_DIR.parent / "examples" / "recipes" / "1c-full.dhub.yaml"),
        ),
        help=(
            "Путь к 1С recipe, из которого берётся object_filters "
            "(default: $ONEC_RECIPE или examples/recipes/1c-full.dhub.yaml)"
        ),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ONEC_BASE_URL"),
        help="URL API сервиса 1С (default: $ONEC_BASE_URL или source.config.base_url)",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("ONEC_USERNAME"),
        help="Логин 1С (default: $ONEC_USERNAME или source.config.username)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("ONEC_PASSWORD", ""),
        help="Пароль 1С (default: $ONEC_PASSWORD или source.config.password)",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("POSTGRES_DATABASE"),
        help=(
            "Фильтр базы данных (default: $POSTGRES_DATABASE, "
            "source.config.postgres.database, $ONEC_INFOBASE_NAME или 1c-test)"
        ),
    )
    parser.add_argument(
        "--schema",
        default=os.environ.get("POSTGRES_SCHEMA"),
        help=(
            "Фильтр схемы (default: $POSTGRES_SCHEMA, "
            "source.config.postgres.schema или public)"
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Вывести в stderr список найденных таблиц.",
    )
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help=(
            "При ошибке или пустом результате вернуть safe-default '(?!)' "
            "и exit 0. Для штатного ingest не использовать."
        ),
    )
    return parser.parse_args()


def _expand_env(value: Any, *, environ: Mapping[str, str] | None = None) -> Any:
    """Раскрыть `${VAR}` и `${VAR:-default}` в строковых recipe-значениях."""
    if not isinstance(value, str):
        return value
    env = os.environ if environ is None else environ
    return expand(value, nounset=False, environ=env)


def _load_recipe(path: str | Path) -> Mapping[str, Any]:
    """Загрузить YAML recipe."""
    recipe_path = Path(path)
    if not recipe_path.exists() and not recipe_path.is_absolute():
        recipe_path = _DATAHUB_DIR / recipe_path
    with recipe_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"recipe must be a YAML mapping: {recipe_path}")
    return data


def _source_config(recipe: Mapping[str, Any]) -> Mapping[str, Any]:
    source = recipe.get("source") or {}
    if not isinstance(source, Mapping):
        return {}
    config = source.get("config") or {}
    if not isinstance(config, Mapping):
        return {}
    return config


def _object_filters(recipe: Mapping[str, Any]) -> ObjectFiltersConfig:
    """Вернуть нормализованные object_filters из 1С recipe."""
    config = _source_config(recipe)
    filters = config.get("object_filters") or {}
    if not isinstance(filters, Mapping):
        return ObjectFiltersConfig()
    return ObjectFiltersConfig.model_validate(filters)


def _object_scope(recipe: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Вернуть виды и явные имена объектов из 1С recipe.

    Kept as a small compatibility wrapper for older tests/imports. For
    wildcard-by-type entries with an empty object list, names are omitted
    because the scope is type-wide.
    """
    filters = _object_filters(recipe)
    object_names = [
        entry.name
        for entries in filters.include_objects.values()
        for entry in entries
    ]
    return filters.include_types, object_names


def _recipe_postgres_config(recipe: Mapping[str, Any]) -> Mapping[str, Any]:
    postgres = _source_config(recipe).get("postgres") or {}
    if not isinstance(postgres, Mapping):
        return {}
    return postgres


def _resolve_setting(
    *,
    explicit: str | None,
    recipe_value: Any,
    default: str,
) -> str:
    """Выбрать CLI/env значение, иначе recipe, иначе default."""
    if explicit:
        return explicit
    expanded = _expand_env(recipe_value)
    if isinstance(expanded, str) and expanded:
        return expanded
    return default


def _resolve_connection_args(
    *,
    recipe: Mapping[str, Any],
    base_url: str | None,
    username: str | None,
    password: str | None,
) -> tuple[str, str, str]:
    """Разрешить параметры подключения к 1С из CLI/env/recipe."""
    config = _source_config(recipe)
    resolved_base_url = _resolve_setting(
        explicit=base_url,
        recipe_value=config.get("base_url"),
        default="",
    )
    resolved_username = _resolve_setting(
        explicit=username,
        recipe_value=config.get("username"),
        default="",
    )
    resolved_password = _resolve_setting(
        explicit=password,
        recipe_value=config.get("password"),
        default="",
    )
    if not resolved_base_url:
        raise ValueError("ONEC_BASE_URL is empty and source.config.base_url is not set")
    if not resolved_username:
        raise ValueError("ONEC_USERNAME is empty and source.config.username is not set")
    return resolved_base_url, resolved_username, resolved_password


def _resolve_pg_scope(
    *,
    recipe: Mapping[str, Any],
    database: str | None,
    schema: str | None,
) -> tuple[str, str]:
    """Разрешить database/schema для regex из CLI/env/recipe."""
    postgres = _recipe_postgres_config(recipe)
    source_config = _source_config(recipe)
    infobase = source_config.get("infobase") or {}
    recipe_infobase_name = infobase.get("name") if isinstance(infobase, Mapping) else None
    default_database = _resolve_setting(
        explicit=None,
        recipe_value=recipe_infobase_name,
        default="1c-test",
    )
    return (
        _resolve_setting(
            explicit=database,
            recipe_value=postgres.get("database"),
            default=default_database,
        ),
        _resolve_setting(
            explicit=schema,
            recipe_value=postgres.get("schema"),
            default="public",
        ),
    )


def _collect_table_names(
    *,
    client: Any,
    object_filters: ObjectFiltersConfig,
    debug: bool = False,
) -> list[str]:
    """Достать lowercase-имена PG-таблиц из 1С ``/db-mapping``."""
    table_names: set[str] = set()

    summaries = client.list_objects(types=object_filters.include_types or None)
    for summary in summaries:
        if not object_filters.includes_object(summary.object_type, summary.name):
            continue
        if summary.object_type == "Constants":
            if debug:
                print(
                    "[pg_tables_pattern] INFO: constants have no 1:1 DB "
                    f"sibling table, skipping {summary.object_type}.{summary.name}",
                    file=sys.stderr,
                )
            continue
        try:
            mapping = client.get_db_mapping(summary.object_type, summary.name)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                if debug:
                    print(
                        "[pg_tables_pattern] WARN: /db-mapping not found for "
                        f"{summary.object_type}.{summary.name}, skipping",
                        file=sys.stderr,
                    )
                continue
            raise

        for table in mapping.tables:
            if (
                getattr(table, "purpose", None) == TABLE_PURPOSE_TABULAR_SECTION
                and getattr(table, "tabular_section_name", None) is not None
                and not object_filters.includes_tabular_section(
                    summary.object_type,
                    summary.name,
                    table.tabular_section_name,
                )
            ):
                continue
            if table.db_table_name:
                table_names.add(pg_normalize(table.db_table_name))

    return sorted(table_names)


def _build_regex(*, database: str, schema: str, table_names: list[str]) -> str:
    r"""Собрать один regex из списка имён таблиц.

    В DataHub SQL-коннекторах ``table_pattern`` применяется к полному
    имени таблицы (в отчёте оно выглядит как ``db.schema.table``), а не
    только к последнему сегменту. Поэтому regex должен матчить
    ``<database>.<schema>.<table>``.

    Используем ``\Z`` вместо ``$`` как end-anchor: значение прокидывается
    через Makefile, где одиночный ``$`` легко потерять при expansion.
    Для Python regex это эквивалентный, но make-safe якорь конца строки.
    """
    if not table_names:
        # Пустой список → regex, не матчащий ничего. Это намеренно:
        # лучше «ничего не загрузим, увидим warning» чем «загрузим
        # тысячи системных _Reference*/_AccumRg*».
        return r"(?!)"
    prefix = f"{re.escape(database.lower())}\\.{re.escape(schema.lower())}\\."
    escaped = [re.escape(t) for t in table_names]
    return prefix + "(" + "|".join(escaped) + r")\Z"


def main() -> int:
    args = _parse_args()
    try:
        recipe = _load_recipe(args.recipe)
        object_filters = _object_filters(recipe)
        database, schema = _resolve_pg_scope(
            recipe=recipe,
            database=args.database,
            schema=args.schema,
        )
        base_url, username, password = _resolve_connection_args(
            recipe=recipe,
            base_url=args.base_url,
            username=args.username,
            password=args.password,
        )
        with OneCApiClient(base_url, username, password) as client:
            table_names = _collect_table_names(
                client=client,
                object_filters=object_filters,
                debug=args.debug,
            )
    except Exception as exc:
        level = "WARN" if args.best_effort else "ERROR"
        print(
            f"[pg_tables_pattern] {level}: не удалось собрать таблицы из 1С "
            f"recipe/API ({args.recipe}): {exc}.\n"
            f"[pg_tables_pattern] Проверь ONEC_BASE_URL/ONEC_USERNAME "
            f"и доступность /db-mapping.",
            file=sys.stderr,
        )
        if args.best_effort:
            print("[pg_tables_pattern] Возвращаю safe-default '(?!)'.", file=sys.stderr)
            print("(?!)", end="")
            return 0
        return 1

    if not table_names:
        level = "WARN" if args.best_effort else "ERROR"
        print(
            f"[pg_tables_pattern] {level}: /db-mapping не вернул ни одной "
            f"PG-таблицы для recipe scope '{args.recipe}'.",
            file=sys.stderr,
        )
        if args.best_effort:
            print("[pg_tables_pattern] Возвращаю safe-default '(?!)'.", file=sys.stderr)
            print("(?!)", end="")
            return 0
        return 1

    if args.debug:
        print(
            f"[pg_tables_pattern] Найдено {len(table_names)} PG-таблиц "
            f"для allow-фильтра в схеме {database}.{schema}:",
            file=sys.stderr,
        )
        include_types = object_filters.include_types
        object_names = [
            entry.name
            for entries in object_filters.include_objects.values()
            for entry in entries
        ]
        if include_types:
            print(
                "[pg_tables_pattern] include_objects types: " + ", ".join(include_types),
                file=sys.stderr,
            )
        if object_names:
            print(
                "[pg_tables_pattern] include_objects names: " + ", ".join(object_names),
                file=sys.stderr,
            )
        for t in table_names:
            print(f"  {t}", file=sys.stderr)

    print(
        _build_regex(
            database=database,
            schema=schema,
            table_names=table_names,
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
