from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from datahub_1c.config import (
    InfobaseConfig,
    IngestionOptionsConfig,
    IntegrationServicesConfig,
    MetadataUuidSourceConfig,
    ObjectFiltersConfig,
    OneCSourceConfig,
    TransliterationConfig,
)
from datahub_1c.mapping.urn import ObjectKind

# Валидный XML для config-тестов, где важен только существующий путь.
_EMPTY_CONFIG_DUMP_XML: str = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
    "<ConfigVersions/>"
    "</ConfigDumpInfo>"
)


@pytest.fixture()
def config_dump_info_path(tmp_path: Path) -> Path:
    p = tmp_path / "ConfigDumpInfo.xml"
    p.write_text(_EMPTY_CONFIG_DUMP_XML, encoding="utf-8")
    return p


def _minimal_recipe(config_dump_info_path: Path) -> dict[str, object]:
    return {
        "base_url": "http://1c-host/1c-test/hs/metadataservice",
        "username": "Администратор",
        "password": "",
        "infobase": {"name": "1c-test", "display_name": "1c-test"},
        "metadata_uuid_source": {"config_dump_info_path": str(config_dump_info_path)},
    }


class TestMinimalRecipe:
    def test_loads_with_defaults(self, config_dump_info_path: Path) -> None:
        cfg = OneCSourceConfig(**_minimal_recipe(config_dump_info_path))
        assert str(cfg.base_url).startswith("http://1c-host")
        assert cfg.username == "Администратор"
        assert cfg.env == "PROD"
        assert cfg.infobase.name == "1c-test"
        assert cfg.infobase.display == "1c-test"
        assert cfg.transliteration.overrides == {}
        assert cfg.object_filters.include_objects == {}
        assert cfg.object_filters.include_types == []
        assert cfg.integration_services.enabled is False
        assert cfg.integration_services.include_types == []
        assert cfg.ingestion.attributes is True
        assert cfg.ingestion.tabular_sections is True
        assert cfg.ingestion.column_lineage is False
        # db_mapping по умолчанию выключен: чтобы минимальный recipe
        # без секции postgres проходил валидацию.
        assert cfg.ingestion.db_mapping is False
        assert cfg.ingestion.emit_db_siblings is True
        assert cfg.postgres.platform_instance is None
        assert cfg.postgres.database is None
        assert cfg.pg_database() == "1c-test"
        assert cfg.postgres.schema_name == "public"
        assert cfg.metadata_uuid_source.config_dump_info_path == config_dump_info_path

    def test_password_never_leaks_in_repr(self, config_dump_info_path: Path) -> None:
        cfg = OneCSourceConfig(
            base_url="http://1c-host/1c-test/hs/metadataservice",
            username="u",
            password="topsecret",
            infobase={"name": "1c-test"},
            metadata_uuid_source={"config_dump_info_path": str(config_dump_info_path)},
        )
        assert "topsecret" not in repr(cfg)
        assert cfg.password.get_secret_value() == "topsecret"


class TestFullRecipe:
    def test_all_fields(self, config_dump_info_path: Path) -> None:
        cfg = OneCSourceConfig(
            base_url="https://1c.example.com/prod/hs/metadataservice",
            username="user",
            password="pw",
            env="DEV",
            infobase={"name": "erp-prod", "display_name": "ERP Production"},
            metadata_uuid_source={"config_dump_info_path": str(config_dump_info_path)},
            transliteration={"overrides": {"ПоступлениеТоваров": "GoodsReceipt"}},
            object_filters={
                "include_objects": [
                    {
                        "Documents": [
                            {
                                "name": "ПоступлениеТоваров",
                                "ingest_tabular_sections": True,
                                "tabular_sections": ["Товары"],
                            },
                        ],
                    },
                    {"Catalogs": ["Номенклатура"]},
                ],
                "common_filters": {
                    "tabular_sections": ["ДополнительныеРеквизиты"],
                },
            },
            integration_services={
                "include_services": {
                    "HTTPServices": [
                        {
                            "name": "OrdersApi",
                            "endpoints": [
                                "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
                            ],
                        },
                    ],
                    "WebServices": ["Exchange"],
                },
            },
            ingestion={
                "attributes": True,
                "tabular_sections": True,
                "lineage": True,
                "lineage_kinds": ["basis", "manual_dataset_flow"],
                "column_lineage": True,
                "db_mapping": True,
                "emit_db_siblings": False,
            },
            postgres={
                "platform_instance": "prod-pg",
                "database": "1c-test",
                "schema": "onec",
            },
        )
        assert cfg.env == "DEV"
        assert cfg.infobase.name == "erp-prod"
        assert cfg.infobase.display == "ERP Production"
        assert cfg.transliteration.overrides["ПоступлениеТоваров"] == "GoodsReceipt"
        assert cfg.object_filters.object_kinds() == [ObjectKind.DOCUMENT, ObjectKind.CATALOG]
        assert cfg.object_filters.includes_object("Documents", "ПоступлениеТоваров")
        assert not cfg.object_filters.includes_object("Documents", "РасходнаяНакладная")
        assert cfg.object_filters.includes_tabular_section(
            "Documents",
            "ПоступлениеТоваров",
            "Товары",
        )
        assert not cfg.object_filters.includes_tabular_section(
            "Documents",
            "ПоступлениеТоваров",
            "ДополнительныеРеквизиты",
        )
        assert cfg.postgres.database == "1c-test"
        assert cfg.postgres.schema_name == "onec"
        assert cfg.integration_services.enabled is True
        assert cfg.integration_services.include_types == ["HTTPServices", "WebServices"]
        assert cfg.integration_services.service_full_names() == [
            "HTTPService.OrdersApi",
            "WebService.Exchange",
        ]
        assert cfg.integration_services.endpoint_full_names() == [
            "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
        ]
        assert cfg.ingestion.lineage_kinds == ["basis", "manual_dataset_flow"]
        assert cfg.ingestion.effective_lineage_kinds == (
            "basis",
            "manual_dataset_flow",
        )
        assert cfg.ingestion.column_lineage is True
        assert cfg.ingestion.emit_db_siblings is False
        # pg_env() по умолчанию равен env; override появляется, если
        # задать postgres.env явно.
        assert cfg.pg_env() == "DEV"


class TestPostgresConfig:
    def test_db_mapping_defaults_database_to_infobase(self, config_dump_info_path: Path) -> None:
        recipe = _minimal_recipe(config_dump_info_path)
        recipe["infobase"] = {"name": "erp-prod"}
        cfg = OneCSourceConfig(
            **recipe,
            ingestion={"db_mapping": True},
        )
        assert cfg.postgres.database is None
        assert cfg.pg_database() == "erp-prod"

    def test_db_mapping_enabled_with_database(self, config_dump_info_path: Path) -> None:
        cfg = OneCSourceConfig(
            **_minimal_recipe(config_dump_info_path),
            ingestion={"db_mapping": True},
            postgres={"database": "1c-test"},
        )
        assert cfg.ingestion.db_mapping is True
        assert cfg.postgres.database == "1c-test"
        assert cfg.pg_database() == "1c-test"
        assert cfg.postgres.schema_name == "public"

    def test_db_mapping_empty_database_rejected(self, config_dump_info_path: Path) -> None:
        with pytest.raises(ValidationError):
            OneCSourceConfig(
                **_minimal_recipe(config_dump_info_path),
                ingestion={"db_mapping": True},
                postgres={"database": "  "},
            )

    def test_pg_env_overrides_main_env(self, config_dump_info_path: Path) -> None:
        cfg = OneCSourceConfig(
            **_minimal_recipe(config_dump_info_path),
            env="DEV",
            ingestion={"db_mapping": True},
            postgres={"database": "1c-test", "env": "PROD"},
        )
        assert cfg.env == "DEV"
        assert cfg.pg_env() == "PROD"


class TestMetadataUuidSourceConfig:
    def test_field_is_required(self) -> None:
        with pytest.raises(ValidationError) as ei:
            OneCSourceConfig(
                base_url="http://1c-host/x",
                username="u",
                password="p",
                infobase={"name": "1c-test"},
            )
        assert "metadata_uuid_source" in str(ei.value)

    def test_path_must_exist(self, tmp_path: Path) -> None:
        missing = tmp_path / "no_such.xml"
        with pytest.raises(ValidationError) as ei:
            MetadataUuidSourceConfig(config_dump_info_path=missing)
        assert "не существует" in str(ei.value)

    def test_path_must_be_file_not_dir(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError) as ei:
            MetadataUuidSourceConfig(config_dump_info_path=tmp_path)
        assert "не является файлом" in str(ei.value)

    def test_tilde_expanded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # Используем tmp_path как поддельный $HOME, кладём в него файл и
        # подсовываем путь с `~`.
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "ConfigDumpInfo.xml").write_text(_EMPTY_CONFIG_DUMP_XML, encoding="utf-8")
        cfg = MetadataUuidSourceConfig(config_dump_info_path=Path("~/ConfigDumpInfo.xml"))
        assert cfg.config_dump_info_path == tmp_path / "ConfigDumpInfo.xml"


class TestExtraFieldsForbidden:
    def test_typo_in_root(self, config_dump_info_path: Path) -> None:
        bad = dict(_minimal_recipe(config_dump_info_path), unexpected_field="x")
        with pytest.raises(ValidationError) as ei:
            OneCSourceConfig(**bad)
        assert "unexpected_field" in str(ei.value)

    def test_typo_in_nested(self, config_dump_info_path: Path) -> None:
        bad = dict(
            _minimal_recipe(config_dump_info_path),
            ingestion={"column-lineage": True},
        )
        with pytest.raises(ValidationError):
            OneCSourceConfig(**bad)


class TestObjectFilters:
    def test_empty_filter_returns_all_kinds(self) -> None:
        f = ObjectFiltersConfig()
        assert set(f.object_kinds()) == set(ObjectKind)

    def test_explicit_filter(self) -> None:
        f = ObjectFiltersConfig(include_objects={"Documents": ["ЗаказПокупателя"]})
        assert f.object_kinds() == [ObjectKind.DOCUMENT]
        assert f.include_types == ["Documents"]
        assert f.includes_object("Documents", "ЗаказПокупателя")
        assert not f.includes_object("Documents", "РасходнаяНакладная")

    @pytest.mark.parametrize(
        "object_type,kind",
        [
            ("Constants", ObjectKind.CONSTANT),
            ("ChartsOfAccounts", ObjectKind.CHART_OF_ACCOUNTS),
            ("ChartsOfCalculationTypes", ObjectKind.CHART_OF_CALCULATION_TYPES),
            ("AccountingRegisters", ObjectKind.ACCOUNTING_REGISTER),
            ("CalculationRegisters", ObjectKind.CALCULATION_REGISTER),
            ("Enums", ObjectKind.ENUMERATION),
        ],
    )
    def test_extended_object_types_are_valid(self, object_type: str, kind: ObjectKind) -> None:
        f = ObjectFiltersConfig(include_objects={object_type: ["X"]})
        assert f.object_kinds() == [kind]
        assert f.include_types == [object_type]

    def test_wildcard_by_type(self) -> None:
        f = ObjectFiltersConfig(include_objects={"Catalogs": []})
        assert f.object_kinds() == [ObjectKind.CATALOG]
        assert f.includes_object("Catalogs", "ЛюбойСправочник")

    def test_list_of_maps_form(self) -> None:
        f = ObjectFiltersConfig(
            include_objects=[
                {
                    "Catalogs": [
                        {
                            "Номенклатура": {
                                "ingest_tabular_sections": True,
                                "tabular_sections": ["Цены"],
                            },
                        },
                    ],
                },
            ],
        )
        assert f.includes_object("Catalogs", "Номенклатура")
        assert f.includes_tabular_section("Catalogs", "Номенклатура", "Цены")
        assert not f.includes_tabular_section("Catalogs", "Номенклатура", "Штрихкоды")

    def test_common_tabular_sections_deny_list_wins(self) -> None:
        f = ObjectFiltersConfig(
            include_objects={"Documents": ["ЗаказПокупателя"]},
            common_filters={"tabular_sections": ["ДополнительныеРеквизиты"]},
        )
        assert not f.includes_tabular_section(
            "Documents",
            "ЗаказПокупателя",
            "ДополнительныеРеквизиты",
        )

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            ObjectFiltersConfig(include_objects={"Микроконтроллеры": []})
        assert "unknown 1C object API type" in str(ei.value)

    def test_legacy_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObjectFiltersConfig(include_types=["Documents"])

    def test_duplicate_object_entry_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            ObjectFiltersConfig(
                include_objects={
                    "Documents": ["ЗаказПокупателя", "ЗаказПокупателя"],
                },
            )
        assert "duplicate object filter entry" in str(ei.value)


class TestIntegrationServicesConfig:
    def test_explicit_service_and_endpoint_filter(self) -> None:
        f = IntegrationServicesConfig(
            include_services={
                "HTTPServices": [
                    {
                        "name": "OrdersApi",
                        "endpoints": [
                            "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
                        ],
                    },
                ],
            },
        )
        assert f.enabled
        assert f.include_types == ["HTTPServices"]
        assert f.service_full_names() == ["HTTPService.OrdersApi"]
        assert f.includes_service("HTTPServices", "OrdersApi")
        assert not f.includes_service("HTTPServices", "MetadataService")
        assert f.includes_endpoint(
            "HTTPServices",
            "OrdersApi",
            "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
        )
        assert not f.includes_endpoint(
            "HTTPServices",
            "OrdersApi",
            "HTTPService.OrdersApi.URLTemplate.Orders.Method.Get",
        )

    def test_wildcard_by_type(self) -> None:
        f = IntegrationServicesConfig(include_services={"HTTPServices": []})
        assert f.include_types == ["HTTPServices"]
        assert f.service_full_names() == []
        assert f.includes_service("HTTPServices", "ЛюбойСервис")
        assert f.includes_endpoint(
            "HTTPServices",
            "ЛюбойСервис",
            "HTTPService.ЛюбойСервис.URLTemplate.Root.Method.Get",
        )

    def test_list_of_maps_form(self) -> None:
        f = IntegrationServicesConfig(
            include_services=[
                {
                    "WebServices": [
                        {
                            "Exchange": {
                                "endpoints": ["WebService.Exchange.Operation.Send"],
                            },
                        },
                    ],
                },
            ],
        )
        assert f.service_full_names() == ["WebService.Exchange"]
        assert f.endpoint_full_names() == ["WebService.Exchange.Operation.Send"]

    def test_unknown_service_type_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            IntegrationServicesConfig(include_services={"Reports": []})
        assert "unknown 1C integration service type" in str(ei.value)

    def test_duplicate_service_entry_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            IntegrationServicesConfig(
                include_services={"HTTPServices": ["OrdersApi", "OrdersApi"]},
            )
        assert "duplicate integration service filter entry" in str(ei.value)


class TestIngestionOptions:
    def test_lineage_kinds_default_to_all_supported_kinds(self) -> None:
        opts = IngestionOptionsConfig(lineage=True)
        assert opts.lineage_kinds is None
        assert opts.effective_lineage_kinds == (
            "basis",
            "register_movement",
            "manual_dataset_flow",
        )

    def test_lineage_kinds_can_be_empty(self) -> None:
        opts = IngestionOptionsConfig(lineage=True, lineage_kinds=[])
        assert opts.effective_lineage_kinds == ()

    def test_lineage_kinds_reject_unknown_values(self) -> None:
        with pytest.raises(ValidationError) as ei:
            IngestionOptionsConfig(lineage_kinds=["selection_criterion"])
        assert "unsupported ingestion.lineage_kinds value" in str(ei.value)

    def test_lineage_kinds_reject_duplicates(self) -> None:
        with pytest.raises(ValidationError) as ei:
            IngestionOptionsConfig(lineage_kinds=["basis", "basis"])
        assert "duplicate ingestion.lineage_kinds value" in str(ei.value)

    def test_lineage_kinds_require_lineage_enabled(self) -> None:
        with pytest.raises(ValidationError) as ei:
            IngestionOptionsConfig(lineage=False, lineage_kinds=["basis"])
        assert "lineage_kinds can be specified only when lineage=True" in str(ei.value)

    def test_column_lineage_requires_lineage(self) -> None:
        with pytest.raises(ValidationError) as ei:
            IngestionOptionsConfig(lineage=False, column_lineage=True)
        assert "column_lineage=True requires lineage=True" in str(ei.value)

    def test_all_off_is_valid(self) -> None:
        opts = IngestionOptionsConfig(
            attributes=False,
            tabular_sections=False,
            lineage=False,
            column_lineage=False,
            db_mapping=False,
            emit_db_siblings=False,
        )
        assert opts.attributes is False
        assert opts.emit_db_siblings is False

    def test_emit_db_siblings_false_requires_custom_aspects_for_db_mapping(self) -> None:
        with pytest.raises(ValidationError) as ei:
            IngestionOptionsConfig(
                db_mapping=True,
                emit_db_siblings=False,
                emit_custom_aspects=False,
            )
        assert "emit_db_siblings=False with db_mapping=True requires" in str(ei.value)


class TestTransliterationConfig:
    def test_non_ascii_value_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            TransliterationConfig(overrides={"Х": "Икс"})
        assert "must be ASCII" in str(ei.value)

    def test_empty_value_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            TransliterationConfig(overrides={"ПоступлениеТоваров": ""})
        assert "must be non-empty" in str(ei.value)

    @pytest.mark.parametrize("value", ["Goods Receipt", "Goods-Receipt"])
    def test_non_identifier_value_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError) as ei:
            TransliterationConfig(overrides={"ПоступлениеТоваров": value})
        assert "must match ^[A-Za-z0-9_]+$" in str(ei.value)


class TestRequiredFields:
    def test_base_url_required(self, config_dump_info_path: Path) -> None:
        with pytest.raises(ValidationError):
            OneCSourceConfig(  # type: ignore[call-arg]
                username="u",
                password="p",
                infobase={"name": "1c-test"},
                metadata_uuid_source={"config_dump_info_path": str(config_dump_info_path)},
            )

    def test_username_non_empty(self, config_dump_info_path: Path) -> None:
        with pytest.raises(ValidationError):
            OneCSourceConfig(
                base_url="http://x",
                username="",
                password="p",
                infobase={"name": "1c-test"},
                metadata_uuid_source={"config_dump_info_path": str(config_dump_info_path)},
            )

    def test_env_non_empty(self, config_dump_info_path: Path) -> None:
        with pytest.raises(ValidationError):
            OneCSourceConfig(**_minimal_recipe(config_dump_info_path), env="")


class TestInfobaseConfig:
    def test_display_defaults_to_name(self) -> None:
        cfg = InfobaseConfig(name="1c-test")
        assert cfg.display == "1c-test"

    def test_display_name_optional_label(self) -> None:
        cfg = InfobaseConfig(name="1c-test", display_name="Тестовая ИБ")
        assert cfg.display == "Тестовая ИБ"

    def test_name_must_be_ascii_stable_id(self) -> None:
        with pytest.raises(ValidationError) as ei:
            InfobaseConfig(name="Тестовая ИБ")
        assert "ASCII" in str(ei.value)

    def test_display_name_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError):
            InfobaseConfig(name="1c-test", display_name=" ")
