"""Эмиссия DB-слоя для объектов 1С.

Коннектор создаёт PG-датасеты-скелеты для всех таблиц из ``/db-mapping``.
Настоящие SQL-типы колонок 1С API не отдаёт, поэтому ``nativeDataType``
заполняется как ``"unknown"`` до запуска обычного Postgres-коннектора.

``Sibling``/``oneCDbMapping``/``mapsToDbTable`` строятся только для
``Main`` и ``TabularSection``: у таблиц итогов регистров нет 1С-датасета-
двойника. ``browsePathsV2`` для PG-датасетов намеренно не эмитится, чтобы
остаться совместимыми с иерархией стандартного Postgres-коннектора.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    OtherSchemaClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SiblingsClass,
    StringTypeClass,
    SubTypesClass,
)

from datahub_1c.api.models import (
    COLUMN_PURPOSE_REFERENCE,
    COLUMN_PURPOSE_REFERENCE_DISCRIMINATOR,
    COLUMN_PURPOSE_TYPE_DISCRIMINATOR,
    COLUMN_PURPOSE_VALUE,
    TABLE_PURPOSE_MAIN,
    TABLE_PURPOSE_TABULAR_SECTION,
    DbColumn,
    DbColumnMapping,
    DbTableMapping,
)
from datahub_1c.mapping.custom_aspects import (
    ONE_C_DB_MAPPING,
    build_custom_aspect_workunit,
)
from datahub_1c.mapping.relationships import (
    REL_MAPS_TO_DB_TABLE,
    build_relationships_workunit,
)
from datahub_1c.mapping.translit import transliterate
from datahub_1c.mapping.urn import (
    pg_dataset_name,
    pg_dataset_urn,
    pg_normalize,
    platform_urn,
)

# SubType должен совпадать со стандартным Postgres-коннектором.
PG_TABLE_SUB_TYPE: str = "Table"

# Явный placeholder для колонок, чей SQL-тип 1С API не отдаёт.
_UNKNOWN_DB_TYPE: str = "unknown"

# columnRole из PDL OneCDbMapping. Маппинг приходящего
# `DbColumn.purpose` (из /db-mapping) в строковое значение, которое
# уходит в payload custom-aspect-а.
_COLUMN_ROLE_VALUE: str = "value"
_COLUMN_ROLE_TYPE: str = "type"
_COLUMN_ROLE_REF: str = "ref"
_COLUMN_ROLE_REF_DISCRIMINATOR: str = "ref_discriminator"

_PURPOSE_TO_ROLE: Mapping[str, str] = {
    COLUMN_PURPOSE_VALUE: _COLUMN_ROLE_VALUE,
    COLUMN_PURPOSE_TYPE_DISCRIMINATOR: _COLUMN_ROLE_TYPE,
    COLUMN_PURPOSE_REFERENCE: _COLUMN_ROLE_REF,
    COLUMN_PURPOSE_REFERENCE_DISCRIMINATOR: _COLUMN_ROLE_REF_DISCRIMINATOR,
}


@dataclass(frozen=True)
class PgDatasetEmission:
    """Результат эмиссии одной PG-таблицы."""

    pg_urn: str
    workunits: Sequence[MetadataWorkUnit]


def is_siblable_purpose(purpose: str) -> bool:
    """True для таблиц с однозначным 1С-датасетом-двойником."""
    return purpose in (TABLE_PURPOSE_MAIN, TABLE_PURPOSE_TABULAR_SECTION)


def _pg_schema_metadata_wu(
    *,
    pg_urn: str,
    db_table_name: str,
    columns: Iterable[DbColumn],
) -> MetadataWorkUnit | None:
    """Колонки нормализуются к lowercase, а типы помечаются как ``unknown``:
    настоящий SQL-тип позже может дописать стандартный PG-коннектор.
    """
    columns_list = list(columns)
    if not columns_list:
        return None

    seen: set[str] = set()
    fields: list[SchemaFieldClass] = []
    for col in columns_list:
        col_name = pg_normalize(col.column_name)
        if col_name in seen:
            # Дубль возникает когда один attribute_name в 1С разворачивается в
            # две колонки PG с одинаковым именем (редко, но возможно при
            # кривых миграциях) — не роняем ingestion, просто пропускаем.
            continue
        seen.add(col_name)
        fields.append(
            SchemaFieldClass(
                fieldPath=col_name,
                type=SchemaFieldDataTypeClass(type=StringTypeClass()),  # type: ignore[no-untyped-call]
                nativeDataType=_UNKNOWN_DB_TYPE,
                nullable=True,
                description=None,
            )
        )

    from datahub.metadata.schema_classes import SchemaMetadataClass  # local import: тяжёлый

    schema = SchemaMetadataClass(
        schemaName=pg_normalize(db_table_name),
        platform=platform_urn("postgres"),
        version=0,
        hash="",
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=fields,
    )
    return MetadataChangeProposalWrapper(entityUrn=pg_urn, aspect=schema).as_workunit()


def build_pg_dataset_workunits(
    *,
    database: str,
    schema: str,
    table: DbTableMapping,
    env: str,
) -> PgDatasetEmission:
    """``container``/``browsePathsV2`` **не эмитим**: дефолтный pipeline-
    трансформер DataHub сам построит path ``database → schema → table``
    из URN, что совпадает с поведением стандартного PG-коннектора.
    """
    pg_table_name = pg_normalize(table.db_table_name)
    pg_urn = pg_dataset_urn(
        database=database, schema=schema, table=table.db_table_name, env=env,
    )
    qualified_name = pg_dataset_name(database, schema, table.db_table_name)

    custom_properties: dict[str, str] = {"table_purpose": table.purpose}
    if table.tabular_section_name:
        custom_properties["tabular_section_name"] = table.tabular_section_name

    workunits: list[MetadataWorkUnit] = []

    workunits.append(
        MetadataChangeProposalWrapper(
            entityUrn=pg_urn,
            aspect=DatasetPropertiesClass(
                name=pg_table_name,
                qualifiedName=qualified_name,
                description=None,
                customProperties=custom_properties,
            ),
        ).as_workunit()
    )
    workunits.append(
        MetadataChangeProposalWrapper(
            entityUrn=pg_urn,
            aspect=SubTypesClass(typeNames=[PG_TABLE_SUB_TYPE]),
        ).as_workunit()
    )

    all_db_columns: list[DbColumn] = []
    for col_map in table.columns:
        all_db_columns.extend(col_map.db_columns)
    # _pg_schema_metadata_wu внутри уже приведёт schemaName/fieldPath
    # к lowercase через pg_normalize — здесь передаём исходное имя.
    schema_wu = _pg_schema_metadata_wu(
        pg_urn=pg_urn, db_table_name=table.db_table_name, columns=all_db_columns,
    )
    if schema_wu is not None:
        workunits.append(schema_wu)

    return PgDatasetEmission(pg_urn=pg_urn, workunits=workunits)


def build_siblings_workunits(
    *,
    onec_urn: str,
    pg_urn: str,
) -> Iterable[MetadataWorkUnit]:
    """Эмитить пару ``Siblings`` (1C primary + PG secondary).

    DataHub UI ожидает аспект на обеих сторонах.
    """
    yield MetadataChangeProposalWrapper(
        entityUrn=onec_urn,
        aspect=SiblingsClass(siblings=[pg_urn], primary=True),
    ).as_workunit()
    yield MetadataChangeProposalWrapper(
        entityUrn=pg_urn,
        aspect=SiblingsClass(siblings=[onec_urn], primary=False),
    ).as_workunit()


def _column_role(purpose: str | None, has_multiple_columns: bool) -> str:
    """Перевести ``DbColumn.purpose`` в columnRole из PDL."""
    if purpose is None:
        return _COLUMN_ROLE_VALUE
    return _PURPOSE_TO_ROLE.get(purpose, _COLUMN_ROLE_VALUE)


def _attribute_columns_payload(
    columns: Iterable[DbColumnMapping],
    *,
    translit_overrides: Mapping[str, str] | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for col_map in columns:
        db_cols = list(col_map.db_columns)
        if not db_cols:
            continue
        try:
            field_path = transliterate(col_map.attribute_name, overrides=translit_overrides)
        except Exception:
            # Транслит не должен ломать db-mapping эмиссию: worst case
            # — UI-плагин не сможет смачить запись с SchemaField, но
            # сам aspect всё равно полезен.
            field_path = col_map.attribute_name
        has_multi = len(db_cols) > 1
        for db_col in db_cols:
            items.append({
                "attributeName": col_map.attribute_name,
                "attributeFieldPath": field_path,
                # DB-neutral имя: 1С может быть развернута поверх разных СУБД,
                # а сервис отдаёт физическое имя колонки без backend-семантики.
                # lowercase — чтобы UI-плагин мог сматчить запись с
                # SchemaField PG-датасета (см. pg_normalize).
                "dbColumnName": pg_normalize(db_col.column_name),
                "columnRole": _column_role(db_col.purpose, has_multi),
            })
    return items


def build_db_mapping_aspect_wu(
    *,
    onec_urn: str,
    table: DbTableMapping,
    translit_overrides: Mapping[str, str] | None = None,
) -> MetadataWorkUnit | None:
    """Если ``attributeColumns`` пустой, aspect не эмитится. Это важно для
    native DataHub UI: generic ``tabular`` renderer v1.5.0.2 строит колонки
    по первой строке массива и не должен получать пустой табличный payload.
    """
    attribute_columns = _attribute_columns_payload(
        table.columns, translit_overrides=translit_overrides,
    )
    if not attribute_columns:
        return None

    payload: dict[str, Any] = {
        # lowercase — соответствует имени реальной таблицы PG и URN
        # PG-датасета-двойника (см. pg_normalize).
        "dbTableName": pg_normalize(table.db_table_name),
        "attributeColumns": attribute_columns,
    }
    return build_custom_aspect_workunit(
        entity_urn=onec_urn,
        entity_type="dataset",
        aspect_name=ONE_C_DB_MAPPING,
        payload=payload,
        workunit_id=f"{onec_urn}-{ONE_C_DB_MAPPING}",
    )


def build_maps_to_db_relationship_wu(
    *,
    onec_urn: str,
    db_urn: str,
) -> MetadataWorkUnit:
    """Typed relationship ``oneCDomainRelationships.mapsToDbTable``."""
    return build_relationships_workunit(
        entity_urn=onec_urn,
        entity_type="dataset",
        relationships={REL_MAPS_TO_DB_TABLE: [db_urn]},
    )
