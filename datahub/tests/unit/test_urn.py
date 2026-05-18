from __future__ import annotations

import pytest

from datahub_1c.mapping.urn import (
    PLATFORM_1C,
    PLATFORM_PG,
    TABULAR_SECTION_SUB_TYPE,
    ObjectKind,
    _legacy_translit_dataset_name,
    container_key,
    container_urn_for,
    dataset_name,
    dataset_urn,
    infobase_container_key,
    infobase_container_urn_for,
    kind_from_plural,
    pg_dataset_name,
    pg_dataset_urn,
    pg_platform_urn,
    platform_urn,
    schema_field_urn_for,
    spec_for,
    type_folder_container_key,
    type_folder_container_urn_for,
    validate_infobase_name,
)

# Каноничные UUID для тестов — лучше один раз зафиксировать, чем плодить
# каждый раз новые: при чтении тест-падений сразу видно, какой именно сегмент
# URN сломался.
DOC_UUID = "88825e44-0d57-41a5-abd8-7a1bdad96c0e"
TS_UUID = "7660073c-26c1-458d-ba3b-7974acb8dceb"
CATALOG_UUID = "deadbeef-0000-0000-0000-000000000001"
INFOBASE = "1c-test"


class TestKindFromPlural:
    @pytest.mark.parametrize(
        "plural,expected",
        [
            ("Constants", ObjectKind.CONSTANT),
            ("Catalogs", ObjectKind.CATALOG),
            ("Documents", ObjectKind.DOCUMENT),
            ("ChartsOfCharacteristicTypes", ObjectKind.CHART_OF_CHARACTERISTIC_TYPES),
            ("ChartsOfAccounts", ObjectKind.CHART_OF_ACCOUNTS),
            ("ChartsOfCalculationTypes", ObjectKind.CHART_OF_CALCULATION_TYPES),
            ("InformationRegisters", ObjectKind.INFORMATION_REGISTER),
            ("AccumulationRegisters", ObjectKind.ACCUMULATION_REGISTER),
            ("AccountingRegisters", ObjectKind.ACCOUNTING_REGISTER),
            ("CalculationRegisters", ObjectKind.CALCULATION_REGISTER),
            ("Enums", ObjectKind.ENUMERATION),
        ],
    )
    def test_known_plurals(self, plural: str, expected: ObjectKind) -> None:
        assert kind_from_plural(plural) == expected

    def test_unknown_plural_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown 1C object API type"):
            kind_from_plural("Микроконтроллеры")


class TestSpec:
    """Полная таблица «вид → (EnglishTerm, SubType)». Если поменяется — тест падает
    и мы обязаны синхронно обновить справочник поддержанных видов."""

    @pytest.mark.parametrize(
        "kind,english_term,sub_type,is_container,supports_tabular_sections,properties_family",
        [
            (ObjectKind.CONSTANT, "Constant", "Constant", False, False, None),
            (ObjectKind.CATALOG, "Catalog", "Catalog", True, True, "catalog"),
            (ObjectKind.DOCUMENT, "Document", "Document", True, True, "document"),
            (ObjectKind.CHART_OF_CHARACTERISTIC_TYPES,
                "ChartOfCharacteristicTypes", "Characteristic Plan", True, True, "catalog"),
            (ObjectKind.CHART_OF_ACCOUNTS,
                "ChartOfAccounts", "Chart of Accounts", True, True, "catalog"),
            (ObjectKind.CHART_OF_CALCULATION_TYPES,
                "ChartOfCalculationTypes", "Chart of Calculation Types", True, True, "catalog"),
            (ObjectKind.INFORMATION_REGISTER,
                "InformationRegister", "Information Register", True, False, "register"),
            (ObjectKind.ACCUMULATION_REGISTER,
                "AccumulationRegister", "Accumulation Register", True, False, "register"),
            (ObjectKind.ACCOUNTING_REGISTER,
                "AccountingRegister", "Accounting Register", True, False, "register"),
            (ObjectKind.CALCULATION_REGISTER,
                "CalculationRegister", "Calculation Register", True, False, "register"),
            (ObjectKind.ENUMERATION, "Enum", "Enumeration", False, False, None),
        ],
    )
    def test_spec_contents(
        self,
        kind: ObjectKind,
        english_term: str,
        sub_type: str,
        is_container: bool,
        supports_tabular_sections: bool,
        properties_family: str | None,
    ) -> None:
        spec = spec_for(kind)
        assert spec.english_term == english_term
        assert spec.sub_type == sub_type
        assert spec.is_container == is_container
        assert spec.supports_tabular_sections == supports_tabular_sections
        assert spec.properties_family == properties_family

    def test_tabular_section_sub_type_is_stable(self) -> None:
        assert TABULAR_SECTION_SUB_TYPE == "Tabular Section"


class TestDatasetName:
    def test_infobase_and_object_uuid(self) -> None:
        assert dataset_name(infobase_name=INFOBASE, object_uuid=DOC_UUID) == (
            f"{INFOBASE}.{DOC_UUID}"
        )

    def test_with_tabular_section(self) -> None:
        assert dataset_name(
            infobase_name=INFOBASE,
            object_uuid=DOC_UUID, tabular_section_uuid=TS_UUID,
        ) == f"{INFOBASE}.{DOC_UUID}.{TS_UUID}"

    def test_no_eng_prefix(self) -> None:
        """ENG-префикс (``Document.``/``Catalog.``) не добавляется."""
        assert dataset_name(infobase_name=INFOBASE, object_uuid=DOC_UUID) == (
            f"{INFOBASE}.{DOC_UUID}"
        )
        assert "Document." not in dataset_name(infobase_name=INFOBASE, object_uuid=DOC_UUID)
        assert "Catalog." not in dataset_name(infobase_name=INFOBASE, object_uuid=CATALOG_UUID)

    def test_uuid_keeps_hyphens(self) -> None:
        """Дефисы UUID сохраняются — это решение зафиксировано в плане."""
        name = dataset_name(
            infobase_name=INFOBASE,
            object_uuid=DOC_UUID,
            tabular_section_uuid=TS_UUID,
        )
        uuid_part = name.removeprefix(f"{INFOBASE}.")
        assert uuid_part.count("-") == 8  # 4 дефиса × 2 UUID

    def test_empty_uuid_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty object UUID"):
            dataset_name(infobase_name=INFOBASE, object_uuid="")

    def test_empty_ts_uuid_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty tabular_section UUID"):
            dataset_name(
                infobase_name=INFOBASE,
                object_uuid=DOC_UUID,
                tabular_section_uuid="",
            )

    def test_invalid_infobase_rejected(self) -> None:
        with pytest.raises(ValueError, match="infobase name"):
            dataset_name(infobase_name="тест", object_uuid=DOC_UUID)


class TestDatasetUrn:
    def test_full_urn_shape(self) -> None:
        urn = dataset_urn(infobase_name=INFOBASE, object_uuid=DOC_UUID, env="PROD")
        assert urn == (
            "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,"
            f"{INFOBASE}.{DOC_UUID},PROD)"
        )

    def test_urn_is_ascii(self) -> None:
        """URN-чисто-ASCII инвариант — UUID-формат гарантирует это by design."""
        urn = dataset_urn(
            infobase_name=INFOBASE,
            object_uuid=DOC_UUID, tabular_section_uuid=TS_UUID, env="PROD",
        )
        assert urn.isascii()

    def test_tabular_section_urn(self) -> None:
        urn = dataset_urn(
            infobase_name=INFOBASE,
            object_uuid=DOC_UUID, tabular_section_uuid=TS_UUID, env="PROD",
        )
        assert f"{INFOBASE}.{DOC_UUID}.{TS_UUID}" in urn

    def test_custom_env(self) -> None:
        urn = dataset_urn(infobase_name=INFOBASE, object_uuid=CATALOG_UUID, env="DEV")
        assert urn.endswith(",DEV)")

    def test_postgres_platform(self) -> None:
        urn = dataset_urn(
            infobase_name=INFOBASE,
            object_uuid=DOC_UUID,
            env="PROD",
            platform=PLATFORM_PG,
        )
        assert "urn:li:dataPlatform:postgres" in urn


class TestInfobaseUrn:
    def test_validate_infobase_name(self) -> None:
        assert validate_infobase_name("  1c-test  ") == "1c-test"

    def test_infobase_key_format(self) -> None:
        assert infobase_container_key(infobase_name=INFOBASE, env="PROD") == (
            f"infobase:{INFOBASE}:PROD"
        )

    def test_infobase_urn_is_ascii(self) -> None:
        urn = infobase_container_urn_for(infobase_name=INFOBASE, env="PROD")
        assert urn.startswith("urn:li:container:")
        assert urn.isascii()


class TestContainerUrn:
    def test_container_key_format(self) -> None:
        assert container_key(
            infobase_name=INFOBASE,
            object_uuid=DOC_UUID,
            env="PROD",
        ) == f"{INFOBASE}:{DOC_UUID}:PROD"

    def test_container_key_env_scoped(self) -> None:
        """В разных env — разные ключи контейнера."""
        prod = container_key(infobase_name=INFOBASE, object_uuid=CATALOG_UUID, env="PROD")
        dev = container_key(infobase_name=INFOBASE, object_uuid=CATALOG_UUID, env="DEV")
        assert prod != dev

    def test_container_key_infobase_scoped(self) -> None:
        prod = container_key(infobase_name="1c-prod", object_uuid=CATALOG_UUID, env="PROD")
        test = container_key(infobase_name="1c-test", object_uuid=CATALOG_UUID, env="PROD")
        assert prod != test

    def test_container_urn_is_ascii(self) -> None:
        urn = container_urn_for(infobase_name=INFOBASE, object_uuid=CATALOG_UUID, env="PROD")
        assert urn.startswith("urn:li:container:")
        assert urn.isascii()

    def test_container_urn_stable_for_same_input(self) -> None:
        """Детерминированность: одинаковые входные данные → одинаковый URN."""
        a = container_urn_for(infobase_name=INFOBASE, object_uuid=CATALOG_UUID, env="PROD")
        b = container_urn_for(infobase_name=INFOBASE, object_uuid=CATALOG_UUID, env="PROD")
        assert a == b


class TestTypeFolderUrn:
    def test_type_folder_key_is_infobase_scoped(self) -> None:
        assert type_folder_container_key(
            ObjectKind.DOCUMENT,
            infobase_name=INFOBASE,
            env="PROD",
        ) == f"{INFOBASE}:Documents:PROD"

    def test_type_folder_urn_differs_by_infobase(self) -> None:
        a = type_folder_container_urn_for(
            ObjectKind.DOCUMENT,
            infobase_name="1c-test",
            env="PROD",
        )
        b = type_folder_container_urn_for(
            ObjectKind.DOCUMENT,
            infobase_name="1c-prod",
            env="PROD",
        )
        assert a != b


class TestSchemaFieldUrn:
    def test_schema_field_urn(self) -> None:
        ds = dataset_urn(infobase_name=INFOBASE, object_uuid=DOC_UUID, env="PROD")
        urn = schema_field_urn_for(ds, "Nomenklatura")
        assert urn.startswith("urn:li:schemaField:")
        assert "Nomenklatura" in urn


class TestPlatformUrn:
    def test_default(self) -> None:
        assert platform_urn() == f"urn:li:dataPlatform:{PLATFORM_1C}"

    def test_postgres(self) -> None:
        assert platform_urn(PLATFORM_PG) == f"urn:li:dataPlatform:{PLATFORM_PG}"


class TestPgDatasetUrn:
    """PG URN не меняется при переходе на UUID-URN на 1С-стороне.

    Формат — ``<database>.<schema>.<table>`` с lowercase-нормализацией
    (см. ``pg_normalize`` и :func:`pg_dataset_name`). Это обеспечивает
    переход к гибридному режиму с DataHub PG-коннектором.
    """

    def test_pg_platform_urn(self) -> None:
        assert pg_platform_urn() == "urn:li:dataPlatform:postgres"

    def test_pg_dataset_name_format(self) -> None:
        assert pg_dataset_name("1c-test", "public", "_Reference42") == (
            "1c-test.public._reference42"
        )

    def test_pg_dataset_name_normalizes_database_and_schema_too(self) -> None:
        assert pg_dataset_name("MyDB", "MySchema", "_T") == "mydb.myschema._t"

    def test_pg_dataset_urn_format(self) -> None:
        urn = pg_dataset_urn(
            database="1c-test", schema="public", table="_Reference42", env="DEV",
        )
        assert urn == (
            "urn:li:dataset:(urn:li:dataPlatform:postgres,"
            "1c-test.public._reference42,DEV)"
        )

    def test_pg_dataset_urn_respects_env(self) -> None:
        urn = pg_dataset_urn(database="db", schema="s", table="t", env="PROD")
        assert urn.endswith(",PROD)")

    @pytest.mark.parametrize(
        "db,sch,tbl",
        [("", "public", "t"), ("db", "", "t"), ("db", "public", "")],
    )
    def test_pg_dataset_empty_segments_rejected(
        self, db: str, sch: str, tbl: str,
    ) -> None:
        with pytest.raises(ValueError, match="pg_dataset_name requires non-empty"):
            pg_dataset_name(db, sch, tbl)


class TestLegacyTranslitDatasetName:
    """Транслит-имя живо как display/customProperties helper, не для URN."""

    def test_object_only(self) -> None:
        assert _legacy_translit_dataset_name(
            ObjectKind.DOCUMENT, "ПоступлениеТоваров",
        ) == "Document.PostuplenieTovarov"

    def test_with_tabular_section(self) -> None:
        assert _legacy_translit_dataset_name(
            ObjectKind.DOCUMENT, "ПоступлениеТоваров", tabular_section="Состав",
        ) == "Document.PostuplenieTovarov.Sostav"

    def test_overrides(self) -> None:
        overrides = {"ПоступлениеТоваров": "GoodsReceipt", "Состав": "Lines"}
        assert _legacy_translit_dataset_name(
            ObjectKind.DOCUMENT, "ПоступлениеТоваров",
            tabular_section="Состав", overrides=overrides,
        ) == "Document.GoodsReceipt.Lines"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            _legacy_translit_dataset_name(ObjectKind.DOCUMENT, "")
