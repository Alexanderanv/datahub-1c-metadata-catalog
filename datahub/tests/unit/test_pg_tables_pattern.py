from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_script_module():
    script_path = Path(__file__).parents[2] / "scripts" / "pg_tables_pattern.py"
    spec = importlib.util.spec_from_file_location("pg_tables_pattern", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_regex_matches_fully_qualified_table_name() -> None:
    module = _load_script_module()

    regex = module._build_regex(  # noqa: SLF001 - скриптовый helper тестируем напрямую
        database="1c-test",
        schema="public",
        table_names=["_document164", "_document164_vt27726"],
    )

    assert re.search(regex, "1c-test.public._document164")
    assert re.search(regex, "1c-test.public._document164_vt27726")


def test_build_regex_does_not_match_short_table_name() -> None:
    module = _load_script_module()

    regex = module._build_regex(  # noqa: SLF001 - скриптовый helper тестируем напрямую
        database="1c-test",
        schema="public",
        table_names=["_document164"],
    )

    # DataHub postgres-коннектор применяет table_pattern к полному имени
    # `database.schema.table`, а не к последнему сегменту. Этот тест
    # защищает от регрессии, из-за которой PG-ingest писал только
    # контейнеры, но не перезаписывал schemaMetadata реальными типами.
    assert not re.search(regex, "_document164")


def test_build_regex_empty_matches_nothing() -> None:
    module = _load_script_module()

    regex = module._build_regex(  # noqa: SLF001 - скриптовый helper тестируем напрямую
        database="1c-test",
        schema="public",
        table_names=[],
    )

    assert not re.search(regex, "")
    assert not re.search(regex, "1c-test.public._document164")


def test_collect_table_names_from_1c_db_mapping_scope() -> None:
    module = _load_script_module()

    class FakeClient:
        def list_objects(self, *, types):
            assert types == ["Documents"]
            return [
                SimpleNamespace(object_type="Documents", name="ЗаказПокупателя"),
                SimpleNamespace(object_type="Documents", name="НеИзScope"),
            ]

        def get_db_mapping(self, object_type, name):
            assert object_type == "Documents"
            assert name == "ЗаказПокупателя"
            return SimpleNamespace(
                tables=[
                    SimpleNamespace(db_table_name="_Document164"),
                    SimpleNamespace(db_table_name="_Document164_VT51557"),
                    SimpleNamespace(db_table_name="_Document164_VT51557"),
                ]
            )

    table_names = module._collect_table_names(  # noqa: SLF001
        client=FakeClient(),
        object_filters=module.ObjectFiltersConfig(
            include_objects={"Documents": ["ЗаказПокупателя"]},
        ),
    )

    assert table_names == ["_document164", "_document164_vt51557"]


def test_collect_table_names_respects_include_objects_scope() -> None:
    module = _load_script_module()

    class FakeClient:
        def list_objects(self, *, types):
            assert types == ["Documents"]
            return [
                SimpleNamespace(object_type="Documents", name="ЗаказПокупателя"),
                SimpleNamespace(object_type="Documents", name="Исключить"),
            ]

        def get_db_mapping(self, object_type, name):
            assert object_type == "Documents"
            assert name == "ЗаказПокупателя"
            return SimpleNamespace(
                tables=[
                    SimpleNamespace(db_table_name="_Document164"),
                ]
            )

    table_names = module._collect_table_names(  # noqa: SLF001
        client=FakeClient(),
        object_filters=module.ObjectFiltersConfig(
            include_objects={"Documents": ["ЗаказПокупателя"]},
        ),
    )

    assert table_names == ["_document164"]


def test_collect_table_names_skips_constants_even_if_in_recipe_scope() -> None:
    module = _load_script_module()

    class FakeClient:
        def list_objects(self, *, types):
            assert types == ["Constants", "Documents"]
            return [
                SimpleNamespace(object_type="Constants", name="ВалютаУчёта"),
                SimpleNamespace(object_type="Documents", name="ЗаказПокупателя"),
            ]

        def get_db_mapping(self, object_type, name):
            assert object_type == "Documents"
            assert name == "ЗаказПокупателя"
            return SimpleNamespace(
                tables=[
                    SimpleNamespace(db_table_name="_Document164"),
                ],
            )

    table_names = module._collect_table_names(  # noqa: SLF001
        client=FakeClient(),
        object_filters=module.ObjectFiltersConfig(
            include_objects={
                "Constants": ["ВалютаУчёта"],
                "Documents": ["ЗаказПокупателя"],
            },
        ),
    )

    assert table_names == ["_document164"]


def test_collect_table_names_skips_filtered_tabular_sections() -> None:
    module = _load_script_module()

    class FakeClient:
        def list_objects(self, *, types):
            assert types is None
            return [
                SimpleNamespace(object_type="Documents", name="ЗаказПокупателя"),
            ]

        def get_db_mapping(self, object_type, name):
            assert object_type == "Documents"
            assert name == "ЗаказПокупателя"
            return SimpleNamespace(
                tables=[
                    SimpleNamespace(db_table_name="_Document164", purpose="Main"),
                    SimpleNamespace(
                        db_table_name="_Document164_VT3727",
                        purpose="TabularSection",
                        tabular_section_name="ДополнительныеРеквизиты",
                    ),
                ]
            )

    table_names = module._collect_table_names(  # noqa: SLF001
        client=FakeClient(),
        object_filters=module.ObjectFiltersConfig(
            common_filters={"tabular_sections": ["ДополнительныеРеквизиты"]},
        ),
    )

    assert table_names == ["_document164"]


def test_recipe_scope_and_env_defaults_are_resolved(monkeypatch) -> None:
    module = _load_script_module()
    recipe = {
        "source": {
            "config": {
                "base_url": "${ONEC_BASE_URL}",
                "username": "${ONEC_USERNAME}",
                "password": "${ONEC_PASSWORD:-}",
                "infobase": {
                    "name": "${ONEC_INFOBASE_NAME:-1c-test}",
                },
                "object_filters": {
                    "include_objects": {
                        "Documents": ["ЗаказПокупателя"],
                    },
                },
                "postgres": {
                    "database": "${POSTGRES_DATABASE:-${ONEC_INFOBASE_NAME:-1c-test}}",
                    "schema": "${POSTGRES_SCHEMA:-public}",
                },
            }
        }
    }
    monkeypatch.setenv("ONEC_BASE_URL", "http://1c/hs/metadataservice")
    monkeypatch.setenv("ONEC_USERNAME", "Администратор")
    monkeypatch.setenv("ONEC_INFOBASE_NAME", "erp-dev")
    monkeypatch.setenv("POSTGRES_SCHEMA", "custom")

    assert module._object_scope(recipe) == (["Documents"], ["ЗаказПокупателя"])  # noqa: SLF001
    object_filters = module._object_filters(recipe)  # noqa: SLF001
    assert object_filters.include_types == ["Documents"]
    assert object_filters.includes_object("Documents", "ЗаказПокупателя")
    assert not object_filters.includes_object("Documents", "Черновик")
    assert module._resolve_connection_args(  # noqa: SLF001
        recipe=recipe,
        base_url=None,
        username=None,
        password=None,
    ) == ("http://1c/hs/metadataservice", "Администратор", "")
    assert module._resolve_pg_scope(  # noqa: SLF001
        recipe=recipe,
        database=None,
        schema=None,
    ) == ("erp-dev", "custom")


def test_main_fails_fast_on_empty_table_list(monkeypatch, capsys) -> None:
    module = _load_script_module()

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(sys, "argv", ["pg_tables_pattern.py"])
    monkeypatch.setattr(module, "_load_recipe", lambda _: {})
    monkeypatch.setattr(module, "_object_filters", lambda _: module.ObjectFiltersConfig())
    monkeypatch.setattr(module, "_resolve_pg_scope", lambda **_: ("1c-test", "public"))
    monkeypatch.setattr(module, "_resolve_connection_args", lambda **_: ("http://1c", "u", "p"))
    monkeypatch.setattr(module, "OneCApiClient", lambda *args: FakeClient())
    monkeypatch.setattr(module, "_collect_table_names", lambda **_: [])

    assert module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR" in captured.err


def test_main_best_effort_returns_safe_default_on_empty_table_list(
    monkeypatch, capsys,
) -> None:
    module = _load_script_module()

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(sys, "argv", ["pg_tables_pattern.py", "--best-effort"])
    monkeypatch.setattr(module, "_load_recipe", lambda _: {})
    monkeypatch.setattr(module, "_object_filters", lambda _: module.ObjectFiltersConfig())
    monkeypatch.setattr(module, "_resolve_pg_scope", lambda **_: ("1c-test", "public"))
    monkeypatch.setattr(module, "_resolve_connection_args", lambda **_: ("http://1c", "u", "p"))
    monkeypatch.setattr(module, "OneCApiClient", lambda *args: FakeClient())
    monkeypatch.setattr(module, "_collect_table_names", lambda **_: [])

    assert module.main() == 0
    captured = capsys.readouterr()
    assert captured.out == "(?!)"
    assert "WARN" in captured.err
