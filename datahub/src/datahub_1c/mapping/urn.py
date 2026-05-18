"""Построение URN для сущностей 1С в DataHub.

URN 1С-датасета строится из ``<infobase>.<object_uuid>[.<ts_uuid>]``.
UUID берётся из ``ConfigDumpInfo.xml``, приводится к lowercase, дефисы
сохраняются. Тип объекта живёт в ``subTypes`` и ``metadataKind``, поэтому
ENG-префикс в URN не добавляется.

Транслитерация не участвует в URN: она нужна только для legacy display
полей и ``SchemaField.fieldPath`` пользовательских реквизитов. Контейнеры
используют стабильный ключ ``<infobase>:<obj_uuid>:<env>``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from datahub.emitter.mce_builder import (
    make_container_urn,
    make_data_platform_urn,
    make_dataset_urn,
    make_schema_field_urn,
)

from datahub_1c.mapping.translit import is_ascii_identifier, transliterate

PLATFORM_1C = "1c-enterprise"
PLATFORM_PG = "postgres"
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class ObjectKind(StrEnum):
    """Поддерживаемый вид объекта 1С.

    Значение enum-а — русский термин 1С в единственном числе. API-контракт
    использует canonical English plural names (``Catalogs``/``Documents``/...);
    русское значение enum-а остаётся удобным source-of-truth для display labels.
    """

    CONSTANT = "Константа"
    CATALOG = "Справочник"
    DOCUMENT = "Документ"
    CHART_OF_CHARACTERISTIC_TYPES = "ПланВидовХарактеристик"
    CHART_OF_ACCOUNTS = "ПланСчетов"
    CHART_OF_CALCULATION_TYPES = "ПланВидовРасчета"
    INFORMATION_REGISTER = "РегистрСведений"
    ACCUMULATION_REGISTER = "РегистрНакопления"
    ACCOUNTING_REGISTER = "РегистрБухгалтерии"
    CALCULATION_REGISTER = "РегистрРасчета"
    ENUMERATION = "Перечисление"


@dataclass(frozen=True)
class KindSpec:
    """Сопоставление вида 1С с API/display/DataHub-терминами."""

    english_term: str
    sub_type: str
    is_container: bool = True
    supports_tabular_sections: bool = True
    properties_family: str | None = None


_KIND_SPECS: dict[ObjectKind, KindSpec] = {
    ObjectKind.CONSTANT: KindSpec(
        "Constant",
        "Constant",
        is_container=False,
        supports_tabular_sections=False,
    ),
    ObjectKind.CATALOG: KindSpec(
        "Catalog",
        "Catalog",
        properties_family="catalog",
    ),
    ObjectKind.DOCUMENT: KindSpec(
        "Document",
        "Document",
        properties_family="document",
    ),
    ObjectKind.CHART_OF_CHARACTERISTIC_TYPES: KindSpec(
        "ChartOfCharacteristicTypes",
        "Characteristic Plan",
        properties_family="catalog",
    ),
    ObjectKind.CHART_OF_ACCOUNTS: KindSpec(
        "ChartOfAccounts",
        "Chart of Accounts",
        properties_family="catalog",
    ),
    ObjectKind.CHART_OF_CALCULATION_TYPES: KindSpec(
        "ChartOfCalculationTypes",
        "Chart of Calculation Types",
        properties_family="catalog",
    ),
    ObjectKind.INFORMATION_REGISTER: KindSpec(
        "InformationRegister",
        "Information Register",
        supports_tabular_sections=False,
        properties_family="register",
    ),
    ObjectKind.ACCUMULATION_REGISTER: KindSpec(
        "AccumulationRegister",
        "Accumulation Register",
        supports_tabular_sections=False,
        properties_family="register",
    ),
    ObjectKind.ACCOUNTING_REGISTER: KindSpec(
        "AccountingRegister",
        "Accounting Register",
        supports_tabular_sections=False,
        properties_family="register",
    ),
    ObjectKind.CALCULATION_REGISTER: KindSpec(
        "CalculationRegister",
        "Calculation Register",
        supports_tabular_sections=False,
        properties_family="register",
    ),
    ObjectKind.ENUMERATION: KindSpec(
        "Enum",
        "Enumeration",
        is_container=False,
        supports_tabular_sections=False,
    ),
}

_API_TYPE_PLURAL: dict[ObjectKind, str] = {
    ObjectKind.CONSTANT:                      "Constants",
    ObjectKind.CATALOG:                       "Catalogs",
    ObjectKind.DOCUMENT:                      "Documents",
    ObjectKind.CHART_OF_CHARACTERISTIC_TYPES: "ChartsOfCharacteristicTypes",
    ObjectKind.CHART_OF_ACCOUNTS:             "ChartsOfAccounts",
    ObjectKind.CHART_OF_CALCULATION_TYPES:    "ChartsOfCalculationTypes",
    ObjectKind.INFORMATION_REGISTER:          "InformationRegisters",
    ObjectKind.ACCUMULATION_REGISTER:         "AccumulationRegisters",
    ObjectKind.ACCOUNTING_REGISTER:           "AccountingRegisters",
    ObjectKind.CALCULATION_REGISTER:          "CalculationRegisters",
    ObjectKind.ENUMERATION:                   "Enums",
}

_API_TYPE_TO_KIND: dict[str, ObjectKind] = {
    api_type: kind for kind, api_type in _API_TYPE_PLURAL.items()
}

_RUSSIAN_PLURAL: dict[ObjectKind, str] = {
    ObjectKind.CONSTANT:                      "Константы",
    ObjectKind.CATALOG:                       "Справочники",
    ObjectKind.DOCUMENT:                      "Документы",
    ObjectKind.CHART_OF_CHARACTERISTIC_TYPES: "Планы видов характеристик",
    ObjectKind.CHART_OF_ACCOUNTS:             "Планы счетов",
    ObjectKind.CHART_OF_CALCULATION_TYPES:    "Планы видов расчета",
    ObjectKind.INFORMATION_REGISTER:          "Регистры сведений",
    ObjectKind.ACCUMULATION_REGISTER:         "Регистры накопления",
    ObjectKind.ACCOUNTING_REGISTER:           "Регистры бухгалтерии",
    ObjectKind.CALCULATION_REGISTER:          "Регистры расчета",
    ObjectKind.ENUMERATION:                   "Перечисления",
}

TABULAR_SECTION_SUB_TYPE: str = "Tabular Section"

# SubType корневого контейнера-папки для группировки по виду объектов 1С.
# Имя — отдельная строка (не совпадает с SubType конкретных объектов),
# UI-плагин сможет рисовать такие узлы особым иконом.
TYPE_FOLDER_SUB_TYPE: str = "1C Object Kind Folder"

# SubType контейнера информационной базы. Это верхний бизнес-уровень под
# платформой ``1c-enterprise``: ``1C:Enterprise → <infobase> → Documents``.
INFOBASE_CONTAINER_SUB_TYPE: str = "1C Infobase"


def kind_from_plural(plural: str) -> ObjectKind:
    """API 1С использует английские имена типов из терминологии платформы:
    ``Catalogs``, ``Documents``, ``AccumulationRegisters`` и т.п. Русские
    имена остаются только display labels.
    """
    try:
        return _API_TYPE_TO_KIND[plural]
    except KeyError as exc:
        raise ValueError(f"unknown 1C object API type: {plural!r}") from exc


def api_type_plural(kind: ObjectKind) -> str:
    return _API_TYPE_PLURAL[kind]


def russian_plural_label(kind: ObjectKind) -> str:
    return _RUSSIAN_PLURAL[kind]


def russian_singular_label(kind: ObjectKind) -> str:
    return str(kind)


def display_full_name(kind: ObjectKind, object_name: str) -> str:
    return f"{russian_singular_label(kind)}.{object_name}"


def spec_for(kind: ObjectKind) -> KindSpec:
    return _KIND_SPECS[kind]


def _translit(name: str, overrides: Mapping[str, str] | None) -> str:
    """Используется только для display-полей (``customProperties.transliteratedName``,
    ``fieldPath`` пользовательских реквизитов), не для URN.
    """
    if not name:
        raise ValueError("empty 1C object name")
    result = transliterate(name, overrides=overrides)
    if not is_ascii_identifier(result):
        raise ValueError(
            f"transliteration of {name!r} produced non-identifier {result!r}; "
            "check overrides or translit table"
        )
    return result


def _validate_uuid(value: str, *, kind: str) -> str:
    """Гарантировать, что в URN не попадёт мусор вместо UUID.

    Проверка лёгкая (length+symbols), а не regex по hex — чтобы не
    дублировать логику валидации из :mod:`datahub_1c.mapping.metadata_uuid`,
    где UUID уже отнормализован. Цель — ловить очевидные баги вызывающих
    (передали ``None``/пустую строку/RU-имя).
    """
    if not value:
        raise ValueError(f"empty {kind} UUID — cannot build URN")
    return value


def validate_infobase_name(value: str) -> str:
    """Проверить стабильный технический идентификатор информационной базы.

    ``infobase.name`` попадает в dataset/container URN, поэтому держим его
    ASCII/URL-friendly. Человеческое русское имя для UI задаётся отдельным
    ``infobase.display_name``.
    """
    name = value.strip()
    if not name:
        raise ValueError("empty infobase name")
    if not _STABLE_ID_RE.fullmatch(name):
        raise ValueError(
            "infobase name must contain only ASCII letters, digits, '.', '_' or '-'"
        )
    return name


def dataset_name(
    *,
    infobase_name: str,
    object_uuid: str,
    tabular_section_uuid: str | None = None,
) -> str:
    """Сегмент ``name`` внутри dataset URN.

    Возвращает ``<infobase>.<obj_uuid>`` для объекта или
    ``<infobase>.<obj_uuid>.<ts_uuid>`` для табличной части. ENG-префикс не
    добавляется: тип объекта пользователь видит через ``subTypes`` и
    ``customProperties.metadataKind``.

    Эту строку DataHub показывает как ``datasetKey.name``; её же использует
    siblings-слой для построения парного URN (платформа ``postgres``).
    """
    infobase = validate_infobase_name(infobase_name)
    base = f"{infobase}.{_validate_uuid(object_uuid, kind='object')}"
    if tabular_section_uuid is None:
        return base
    ts = _validate_uuid(tabular_section_uuid, kind="tabular_section")
    return f"{base}.{ts}"


def dataset_urn(
    *,
    infobase_name: str,
    object_uuid: str,
    env: str,
    tabular_section_uuid: str | None = None,
    platform: str = PLATFORM_1C,
) -> str:
    return make_dataset_urn(
        platform,
        dataset_name(
            infobase_name=infobase_name,
            object_uuid=object_uuid,
            tabular_section_uuid=tabular_section_uuid,
        ),
        env,
    )


def infobase_container_key(*, infobase_name: str, env: str) -> str:
    infobase = validate_infobase_name(infobase_name)
    if not env:
        raise ValueError("empty env for infobase_container_key")
    return f"infobase:{infobase}:{env}"


def infobase_container_urn_for(*, infobase_name: str, env: str) -> str:
    return make_container_urn(
        infobase_container_key(infobase_name=infobase_name, env=env)
    )


def container_key(*, infobase_name: str, object_uuid: str, env: str) -> str:
    """Стабильный бизнес-ключ контейнера.

    Ключ включает env, чтобы контейнеры в разных средах (PROD/QA/DEV)
    были разными сущностями. Разделитель ``:`` валиден в ``container`` URN
    и отделяет env от UUID объекта.
    """
    infobase = validate_infobase_name(infobase_name)
    obj = _validate_uuid(object_uuid, kind="object")
    if not env:
        raise ValueError("empty env for container_key")
    return f"{infobase}:{obj}:{env}"


def container_urn_for(*, infobase_name: str, object_uuid: str, env: str) -> str:
    """Container URN для объекта 1С, имеющего табличные части.

    Container эмитируется только для тех ``Справочник``/``Документ`` и т.п.,
    у которых в метаданных есть хотя бы одна табличная часть.
    """
    return make_container_urn(
        container_key(infobase_name=infobase_name, object_uuid=object_uuid, env=env)
    )


# Транслит больше не участвует в URN. Оставлен для legacy display-полей и
# fieldPath пользовательских реквизитов.


def _legacy_translit_dataset_name(
    kind: ObjectKind,
    object_name: str,
    *,
    tabular_section: str | None = None,
    overrides: Mapping[str, str] | None = None,
) -> str:
    prefix = spec_for(kind).english_term
    body = _translit(object_name, overrides)
    base = f"{prefix}.{body}"
    if tabular_section is None:
        return base
    return f"{base}.{_translit(tabular_section, overrides)}"


def type_folder_display(kind: ObjectKind) -> str:
    return russian_plural_label(kind)


def type_folder_container_key(
    kind: ObjectKind,
    *,
    infobase_name: str,
    env: str,
) -> str:
    """Стабильный бизнес-ключ type-folder контейнера.

    Env-суффикс — так же, как у object-container, чтобы папки в разных
    окружениях были независимыми. Prefix ИБ нужен, чтобы ``Documents`` разных
    информационных баз были разными контейнерами.
    """
    infobase = validate_infobase_name(infobase_name)
    if not env:
        raise ValueError("empty env for type_folder_container_key")
    return f"{infobase}:{api_type_plural(kind)}:{env}"


def type_folder_container_urn_for(
    kind: ObjectKind,
    *,
    infobase_name: str,
    env: str,
) -> str:
    """Container URN корневой папки вида (``Documents`` / ``Catalogs`` / ...).

    Используется как:
    * parent-container для object-container (``Document.ZakazPokupatelya``);
    * контейнер напрямую для датасетов объектов без ТЧ (справочник без ТЧ,
      регистр, перечисление) — чтобы они тоже группировались в Navigate UI.
    """
    return make_container_urn(
        type_folder_container_key(kind, infobase_name=infobase_name, env=env)
    )


def schema_field_urn_for(
    parent_dataset_urn: str,
    field_path: str,
) -> str:
    """Обёртка над ``make_schema_field_urn``.

    Назначение — единообразно конструировать URN-ы полей для
    ``ForeignKeyConstraint.sourceFields/foreignFields`` и
    ``FineGrainedLineage``.
    """
    return make_schema_field_urn(parent_dataset_urn, field_path)


def platform_urn(platform: str = PLATFORM_1C) -> str:
    return make_data_platform_urn(platform)


# Формат URN здесь *намеренно* повторяет тот, что эмитит стандартный DataHub
# Postgres-коннектор: ``<database>.<schema>.<table>``. Позже можно включить
# параллельный ingestion через `acryl-datahub[postgres]`, и его aspects
# (реальные типы, PK/FK, статистики) сольются с нашими Siblings по URN.
#
# ``platform_instance`` сейчас не используется: в целевом контуре один
# инстанс PG-базы 1С. При необходимости параметр ``postgres.platform_instance``
# можно добавить в recipe без поломки старых URN.


def pg_platform_urn() -> str:
    """URN платформы Postgres."""
    return make_data_platform_urn(PLATFORM_PG)


def pg_normalize(identifier: str) -> str:
    """Нормализовать физическое PG-имя к lowercase.

    Это держит URN совместимыми со стандартным Postgres-коннектором
    DataHub, который читает lowercase-имена из ``information_schema``.
    Не применять к 1С-семантике и enum-значениям.
    """
    return identifier.lower()


def pg_dataset_name(database: str, schema: str, table: str) -> str:
    """Сегмент ``name`` внутри PG dataset URN: ``<db>.<schema>.<table>``."""
    if not database or not schema or not table:
        raise ValueError(
            f"pg_dataset_name requires non-empty database/schema/table "
            f"(got {database!r}/{schema!r}/{table!r})"
        )
    return f"{pg_normalize(database)}.{pg_normalize(schema)}.{pg_normalize(table)}"


def pg_dataset_urn(
    *,
    database: str,
    schema: str,
    table: str,
    env: str,
) -> str:
    """URN PG-датасета для физической таблицы из ``/db-mapping``."""
    return make_dataset_urn(
        PLATFORM_PG,
        pg_dataset_name(database, schema, table),
        env,
    )
