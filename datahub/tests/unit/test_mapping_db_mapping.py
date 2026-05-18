from __future__ import annotations

import json

import pytest

from datahub_1c.api.models import (
    TABLE_PURPOSE_MAIN,
    TABLE_PURPOSE_TABULAR_SECTION,
    TABLE_PURPOSE_TOTALS,
    TABLE_PURPOSE_TOTALS_SLICE_FIRST,
    TABLE_PURPOSE_TOTALS_SLICE_LAST,
    DbColumn,
    DbColumnMapping,
    DbTableMapping,
)
from datahub_1c.mapping.custom_aspects import (
    ONE_C_DB_MAPPING,
    ONE_C_DOMAIN_RELATIONSHIPS,
)
from datahub_1c.mapping.db_mapping import (
    PG_TABLE_SUB_TYPE,
    build_db_mapping_aspect_wu,
    build_maps_to_db_relationship_wu,
    build_pg_dataset_workunits,
    build_siblings_workunits,
    is_siblable_purpose,
)
from datahub_1c.mapping.relationships import REL_MAPS_TO_DB_TABLE

ONEC_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.ZakazPokupatelya,DEV)"
DB = "1c-test"
SCHEMA = "public"
ENV = "DEV"


def _pg_urn(table: str, env: str = ENV) -> str:
    """URN PG-датасета в lowercase."""
    return f"urn:li:dataset:(urn:li:dataPlatform:postgres,{DB}.{SCHEMA}.{table.lower()},{env})"


def _make_table(
    *,
    db_table_name: str = "_Document123",
    purpose: str = TABLE_PURPOSE_MAIN,
    columns: list[DbColumnMapping] | None = None,
) -> DbTableMapping:
    return DbTableMapping(
        db_table_name=db_table_name,
        purpose=purpose,
        columns=columns or [],
    )


class TestIsSiblablePurpose:
    """Проверка таблиц, для которых есть 1С-двойник."""

    @pytest.mark.parametrize("purpose", [
        TABLE_PURPOSE_MAIN,
        TABLE_PURPOSE_TABULAR_SECTION,
    ])
    def test_purposes_with_onec_counterpart_are_siblable(self, purpose: str) -> None:
        assert is_siblable_purpose(purpose) is True

    @pytest.mark.parametrize("purpose", [
        TABLE_PURPOSE_TOTALS,
        TABLE_PURPOSE_TOTALS_SLICE_FIRST,
        TABLE_PURPOSE_TOTALS_SLICE_LAST,
    ])
    def test_register_totals_not_siblable(self, purpose: str) -> None:
        assert is_siblable_purpose(purpose) is False


class TestBuildPgDatasetWorkunits:
    def test_urn_format_matches_standard_postgres_connector(self) -> None:
        table = _make_table(db_table_name="_Document123")
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        assert emission.pg_urn == _pg_urn("_Document123")

    def test_emits_properties_and_subtypes(self) -> None:
        table = _make_table(db_table_name="_Reference42")
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        aspect_names = [wu.metadata.aspectName for wu in emission.workunits]  # type: ignore[union-attr]
        assert "datasetProperties" in aspect_names
        assert "subTypes" in aspect_names
        assert "schemaMetadata" not in aspect_names

    def test_table_purpose_propagated_to_custom_properties(self) -> None:
        """Любая таблица — в customProperties.table_purpose уходит её
        назначение. Это полезно для пользователя UI: видно `Totals` /
        `TabularSection` / `Main` в карточке датасета."""
        table = _make_table(
            db_table_name="_AccumRgT165", purpose=TABLE_PURPOSE_TOTALS,
        )
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        props = next(
            wu.metadata.aspect for wu in emission.workunits
            if wu.metadata.aspectName == "datasetProperties"  # type: ignore[union-attr]
        )
        assert props.customProperties == {"table_purpose": TABLE_PURPOSE_TOTALS}

    def test_tabular_section_name_in_custom_properties(self) -> None:
        """Для ТЧ-таблицы в customProperties добавляется
        tabular_section_name — даёт пользователю на стороне PG быстро
        понять, какой ТЧ соответствует *_VT*-таблица (особенно полезно,
        когда смотришь PG-датасет напрямую, без Sibling-перехода)."""
        table = DbTableMapping(
            db_table_name="_Document142_VT143",
            purpose=TABLE_PURPOSE_TABULAR_SECTION,
            tabular_section_name="Товары",
            columns=[],
        )
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        props = next(
            wu.metadata.aspect for wu in emission.workunits
            if wu.metadata.aspectName == "datasetProperties"  # type: ignore[union-attr]
        )
        assert props.customProperties == {
            "table_purpose": TABLE_PURPOSE_TABULAR_SECTION,
            "tabular_section_name": "Товары",
        }

    def test_no_tabular_section_name_when_main(self) -> None:
        """Для не-ТЧ таблиц tabular_section_name в customProperties не
        попадает (даже если по какой-то причине задан в DTO)."""
        table = _make_table(
            db_table_name="_Document123", purpose=TABLE_PURPOSE_MAIN,
        )
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        props = next(
            wu.metadata.aspect for wu in emission.workunits
            if wu.metadata.aspectName == "datasetProperties"  # type: ignore[union-attr]
        )
        assert "tabular_section_name" not in props.customProperties

    def test_emits_schema_metadata_when_columns_present(self) -> None:
        table = _make_table(
            db_table_name="_Reference42",
            columns=[
                DbColumnMapping(
                    attribute_name="Код",
                    db_columns=[DbColumn(column_name="_Code")],
                ),
            ],
        )
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        aspects = [wu.metadata.aspect for wu in emission.workunits]
        schema_metadata_list = [
            a for a in aspects if getattr(a, "ASPECT_NAME", "") == "schemaMetadata"
        ]
        assert len(schema_metadata_list) == 1
        schema = schema_metadata_list[0]
        assert schema.platform == "urn:li:dataPlatform:postgres"
        # fieldPath — lowercase: реальный PG хранит идентификаторы в
        # lowercase, и стандартный коннектор тоже эмитит lowercase.
        # Без нормализации Sibling-карточка в UI показывала бы
        # "удвоенные" колонки (`_Code` от нас + `_code` от PG-коннектора).
        assert [f.fieldPath for f in schema.fields] == ["_code"]
        # schemaName тоже lowercase — отражает реальное имя таблицы PG.
        assert schema.schemaName == "_reference42"
        # 1С API больше не отдаёт SQL-тип; всегда подставляем "unknown".
        # Стандартный PG-коннектор позже перезапишет настоящими типами.
        assert schema.fields[0].nativeDataType == "unknown"

    def test_subtype_is_table(self) -> None:
        table = _make_table(db_table_name="_T")
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        subtypes = [
            wu for wu in emission.workunits
            if wu.metadata.aspectName == "subTypes"  # type: ignore[union-attr]
        ]
        assert subtypes[0].metadata.aspect.typeNames == [PG_TABLE_SUB_TYPE]

    def test_schema_metadata_dedupes_duplicate_column_names(self) -> None:
        table = _make_table(
            db_table_name="_T",
            columns=[
                DbColumnMapping(
                    attribute_name="A",
                    db_columns=[
                        DbColumn(column_name="_x"),
                        DbColumn(column_name="_x"),
                    ],
                ),
            ],
        )
        emission = build_pg_dataset_workunits(
            database=DB, schema=SCHEMA, table=table, env=ENV,
        )
        schema = next(
            wu.metadata.aspect for wu in emission.workunits
            if wu.metadata.aspectName == "schemaMetadata"  # type: ignore[union-attr]
        )
        assert [f.fieldPath for f in schema.fields] == ["_x"]


class TestBuildSiblingsWorkunits:
    def test_emits_both_directions(self) -> None:
        pg_urn = _pg_urn("_T")
        wus = list(build_siblings_workunits(onec_urn=ONEC_URN, pg_urn=pg_urn))
        assert len(wus) == 2

        by_entity = {wu.metadata.entityUrn: wu.metadata.aspect for wu in wus}
        assert ONEC_URN in by_entity
        assert pg_urn in by_entity

    def test_onec_side_is_primary(self) -> None:
        pg_urn = _pg_urn("_T")
        wus = list(build_siblings_workunits(onec_urn=ONEC_URN, pg_urn=pg_urn))
        onec_wu = next(wu for wu in wus if wu.metadata.entityUrn == ONEC_URN)
        assert onec_wu.metadata.aspect.primary is True
        assert onec_wu.metadata.aspect.siblings == [pg_urn]

    def test_pg_side_is_secondary(self) -> None:
        pg_urn = _pg_urn("_T")
        wus = list(build_siblings_workunits(onec_urn=ONEC_URN, pg_urn=pg_urn))
        pg_wu = next(wu for wu in wus if wu.metadata.entityUrn == pg_urn)
        assert pg_wu.metadata.aspect.primary is False
        assert pg_wu.metadata.aspect.siblings == [ONEC_URN]


class TestBuildDbMappingAspect:
    def test_payload_shape(self) -> None:
        table = _make_table(
            db_table_name="_Document123",
            columns=[
                DbColumnMapping(
                    attribute_name="Номер",
                    db_columns=[DbColumn(column_name="_Number")],
                ),
            ],
        )
        wu = build_db_mapping_aspect_wu(onec_urn=ONEC_URN, table=table)
        assert wu is not None
        assert wu.metadata.aspectName == ONE_C_DB_MAPPING
        assert wu.metadata.entityUrn == ONEC_URN

        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))
        # dbTableName — DB-neutral имя физической таблицы. Lowercase
        # соответствует реальному имени таблицы PG и URN PG-датасета-двойника.
        assert payload["dbTableName"] == "_document123"
        cols = payload["attributeColumns"]
        assert len(cols) == 1
        assert cols[0]["attributeName"] == "Номер"
        # Транслитерация `Номер` ≠ "Номер" — и это входит в payload
        # как `attributeFieldPath`, по которому UI-плагин джойнит
        # с SchemaField.
        assert cols[0]["attributeFieldPath"] != "Номер"
        # dbColumnName — lowercase, как в реальной БД.
        assert cols[0]["dbColumnName"] == "_number"
        assert cols[0]["columnRole"] == "value"

    def test_composite_type_maps_to_multiple_rows_with_roles(self) -> None:
        """Составной тип 1С → несколько колонок СУБД с разными ролями."""
        table = _make_table(
            db_table_name="_Document123",
            columns=[
                DbColumnMapping(
                    attribute_name="Контрагент",
                    db_columns=[
                        DbColumn(column_name="_Fld1_TYPE", purpose="type_discriminator"),
                        DbColumn(column_name="_Fld1RRef", purpose="reference"),
                        DbColumn(column_name="_Fld1", purpose="value"),
                    ],
                ),
            ],
        )
        wu = build_db_mapping_aspect_wu(onec_urn=ONEC_URN, table=table)
        assert wu is not None
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))
        roles = [c["columnRole"] for c in payload["attributeColumns"]]
        assert roles == ["type", "ref", "value"]
        # Проверим заодно, что dbColumnName тоже нормализованы к lowercase
        # — это критично для джойна с SchemaField PG-датасета.
        col_names = [c["dbColumnName"] for c in payload["attributeColumns"]]
        assert col_names == ["_fld1_type", "_fld1rref", "_fld1"]

    def test_reference_discriminator_maps_to_ref_discriminator_role(self) -> None:
        """Новый purpose `reference_discriminator` (для определяемых типов)
        мапится в роль `ref_discriminator` — добавлено в 2026-04 вместе
        с переделкой /db-mapping в 1С-сервисе."""
        table = _make_table(
            db_table_name="_Document123",
            columns=[
                DbColumnMapping(
                    attribute_name="ОснованиеТип",
                    db_columns=[
                        DbColumn(column_name="_Fld1_RTRef", purpose="reference_discriminator"),
                    ],
                ),
            ],
        )
        wu = build_db_mapping_aspect_wu(onec_urn=ONEC_URN, table=table)
        assert wu is not None
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))
        assert payload["attributeColumns"][0]["columnRole"] == "ref_discriminator"

    def test_unknown_purpose_falls_back_to_value(self) -> None:
        """Forward-compat: незнакомый purpose не валит ingestion, мапится в value."""
        table = _make_table(
            db_table_name="_T",
            columns=[
                DbColumnMapping(
                    attribute_name="A",
                    db_columns=[DbColumn(column_name="_x", purpose="mystery")],
                ),
            ],
        )
        wu = build_db_mapping_aspect_wu(onec_urn=ONEC_URN, table=table)
        assert wu is not None
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))
        assert payload["attributeColumns"][0]["columnRole"] == "value"

    def test_does_not_emit_aspect_without_attribute_columns(self) -> None:
        """Native tabular UI needs at least one row in attributeColumns."""
        table = _make_table(
            db_table_name="_T",
            columns=[DbColumnMapping(attribute_name="A", db_columns=[])],
        )
        wu = build_db_mapping_aspect_wu(onec_urn=ONEC_URN, table=table)
        assert wu is None

    def test_translit_overrides_applied(self) -> None:
        table = _make_table(
            db_table_name="_T",
            columns=[
                DbColumnMapping(
                    attribute_name="Номер",
                    db_columns=[DbColumn(column_name="_x")],
                ),
            ],
        )
        wu = build_db_mapping_aspect_wu(
            onec_urn=ONEC_URN,
            table=table,
            translit_overrides={"Номер": "DocNumber"},
        )
        assert wu is not None
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))
        assert payload["attributeColumns"][0]["attributeFieldPath"] == "DocNumber"


class TestBuildMapsToDbRelationship:
    def test_emits_one_target(self) -> None:
        pg_urn = _pg_urn("_T")
        wu = build_maps_to_db_relationship_wu(onec_urn=ONEC_URN, db_urn=pg_urn)
        assert wu.metadata.aspectName == ONE_C_DOMAIN_RELATIONSHIPS
        assert wu.metadata.entityUrn == ONEC_URN
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))
        assert payload == {REL_MAPS_TO_DB_TABLE: [pg_urn]}


@pytest.mark.parametrize(
    "purpose,expected_role",
    [
        (None, "value"),
        ("value", "value"),
        ("type_discriminator", "type"),
        ("reference", "ref"),
        ("reference_discriminator", "ref_discriminator"),
    ],
)
def test_column_role_mapping(purpose: str | None, expected_role: str) -> None:
    """Smoke-test для внутренней функции через публичный API.

    Проверяет всю таблицу маппинга `DbColumn.purpose` → `columnRole`
    из PDL. Параметр `None` — для простых типов, где BSL-сервис не
    выставляет purpose (плагин трактует как value).
    """
    table = _make_table(
        db_table_name="_T",
        columns=[
            DbColumnMapping(
                attribute_name="A",
                db_columns=[DbColumn(column_name="_x", purpose=purpose)],
            ),
        ],
    )
    wu = build_db_mapping_aspect_wu(onec_urn=ONEC_URN, table=table)
    assert wu is not None
    payload = json.loads(wu.metadata.aspect.value.decode("ascii"))
    assert payload["attributeColumns"][0]["columnRole"] == expected_role
