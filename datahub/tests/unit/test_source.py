from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests
from datahub.configuration.common import ConfigurationError
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    BrowsePathsV2Class,
    ContainerClass,
    ContainerPropertiesClass,
    DataFlowInfoClass,
    DataJobInfoClass,
    DataJobInputOutputClass,
    DatasetLineageTypeClass,
    SchemaMetadataClass,
    SiblingsClass,
    StatusClass,
    SubTypesClass,
    UpstreamClass,
    UpstreamLineageClass,
)
from pydantic import ValidationError
from pytest_httpserver import HTTPServer

import datahub_1c.source as source_module
from datahub_1c.config import OneCSourceConfig
from datahub_1c.mapping.custom_aspects import (
    ONE_C_CATALOG_PROPERTIES,
    ONE_C_DB_MAPPING,
    ONE_C_DOCUMENT_PROPERTIES,
    ONE_C_DOMAIN_RELATIONSHIPS,
    ONE_C_OBJECT_PROPERTIES,
    ONE_C_REGISTER_PROPERTIES,
)
from datahub_1c.mapping.lineage import (
    ONEC_DIRECT_LINEAGE_SCOPE,
    ONEC_LINEAGE_MANAGED_BY_PROPERTY,
    ONEC_LINEAGE_MANAGED_BY_VALUE,
    ONEC_LINEAGE_SCOPE_PROPERTY,
)
from datahub_1c.mapping.metadata_uuid import MetadataUuidIndex
from datahub_1c.mapping.relationships import (
    REL_HAS_TABULAR_PART,
    REL_IS_REFERENCED_BY_OBJECT,
    REL_IS_TABULAR_PART_OF,
    REL_MAPS_TO_DB_TABLE,
    REL_REFERS_TO_OBJECT,
)
from datahub_1c.mapping.urn import (
    TABULAR_SECTION_SUB_TYPE,
    ObjectKind,
    infobase_container_urn_for,
    type_folder_container_urn_for,
)
from datahub_1c.source import OneCSource

# Стабильные UUID для объектов/ТЧ, которые упоминаются в тестах.

_OBJECT_UUIDS: dict[tuple[ObjectKind, str], str] = {
    (ObjectKind.CONSTANT, "ВалютаУчёта"): "10101010-1010-1010-1010-101010101001",
    (ObjectKind.DOCUMENT, "ПоступлениеТоваров"): "11111111-1111-1111-1111-111111111101",
    (ObjectKind.DOCUMENT, "ПростойДокумент"): "11111111-1111-1111-1111-111111111102",
    (ObjectKind.DOCUMENT, "ЗаказКлиента"): "11111111-1111-1111-1111-111111111103",
    (ObjectKind.DOCUMENT, "Платёж"): "11111111-1111-1111-1111-111111111104",
    (ObjectKind.CATALOG, "Номенклатура"): "22222222-2222-2222-2222-222222222201",
    (ObjectKind.CATALOG, "Foo"): "22222222-2222-2222-2222-222222222202",
    (ObjectKind.CHART_OF_ACCOUNTS, "Управленческий"): "22222222-2222-2222-2222-222222222203",
    (ObjectKind.CHART_OF_CALCULATION_TYPES, "Начисления"): "22222222-2222-2222-2222-222222222204",
    (ObjectKind.ENUMERATION, "БазыРаспределенияРасходов"): "22222222-2222-2222-2222-222222222205",
    (ObjectKind.INFORMATION_REGISTER, "Курсы"): "33333333-3333-3333-3333-333333333301",
    (ObjectKind.ACCUMULATION_REGISTER, "ОстаткиТоваров"): "33333333-3333-3333-3333-333333333302",
    (ObjectKind.ACCOUNTING_REGISTER, "Управленческий"): "33333333-3333-3333-3333-333333333303",
    (ObjectKind.CALCULATION_REGISTER, "Начисления"): "33333333-3333-3333-3333-333333333304",
}

_TS_UUIDS: dict[tuple[ObjectKind, str, str], str] = {
    (ObjectKind.DOCUMENT, "ПоступлениеТоваров", "Состав"): "44444444-4444-4444-4444-444444444401",
    (ObjectKind.DOCUMENT, "ЗаказКлиента", "Товары"): "44444444-4444-4444-4444-444444444402",
}

_ATTR_UUIDS: dict[tuple[ObjectKind, str, str | None, str], str] = {
    (ObjectKind.CATALOG, "Номенклатура", None, "Артикул"): "55555555-5555-5555-5555-555555555501",
}
_INTEGRATION_SERVICE_UUIDS: dict[tuple[str, str], str] = {
    ("HTTPServices", "OrdersApi"): "66666666-6666-6666-6666-666666666601",
}
_INTEGRATION_ENDPOINT_UUIDS: dict[str, str] = {
    "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post": "77777777-7777-7777-7777-777777777701",
}
_INFOBASE_NAME = "1c-test"


class _FakeGraph:
    def __init__(
        self,
        upstream_lineage_by_urn: dict[str, UpstreamLineageClass | None] | None = None,
    ) -> None:
        self._upstream_lineage_by_urn = upstream_lineage_by_urn or {}

    def get_config(self) -> dict[str, Any]:
        return {}

    def get_aspect(
        self,
        entity_urn: str,
        aspect_type: type,
        version: int = 0,
    ) -> UpstreamLineageClass | None:
        assert aspect_type is UpstreamLineageClass
        assert version == 0
        return self._upstream_lineage_by_urn.get(entity_urn)

    def get_entities(
        self,
        entity_name: str,
        urns: list[str],
        aspects: list[str] | None = None,
        with_system_metadata: bool = False,
    ) -> dict[str, dict[str, tuple[UpstreamLineageClass, None]]]:
        assert entity_name == "dataset"
        assert aspects == [UpstreamLineageClass.ASPECT_NAME]
        assert with_system_metadata is False
        return {
            urn: {UpstreamLineageClass.ASPECT_NAME: (aspect, None)}
            for urn in urns
            if (aspect := self._upstream_lineage_by_urn.get(urn)) is not None
        }


def _build_uuid_index() -> MetadataUuidIndex:
    return MetadataUuidIndex(
        objects=dict(_OBJECT_UUIDS),
        tabular_sections=dict(_TS_UUIDS),
        attributes=dict(_ATTR_UUIDS),
        integration_services=dict(_INTEGRATION_SERVICE_UUIDS),
        integration_endpoints=dict(_INTEGRATION_ENDPOINT_UUIDS),
    )


def _doc_uuid(name: str) -> str:
    return _OBJECT_UUIDS[(ObjectKind.DOCUMENT, name)]


def _cat_uuid(name: str) -> str:
    return _OBJECT_UUIDS[(ObjectKind.CATALOG, name)]


def _object_uuid(kind: ObjectKind, name: str) -> str:
    return _OBJECT_UUIDS[(kind, name)]


def _ts_uuid(parent: str, ts_name: str, kind: ObjectKind = ObjectKind.DOCUMENT) -> str:
    return _TS_UUIDS[(kind, parent, ts_name)]


def _upstream_patch_wus(wus: list[MetadataWorkUnit]) -> list[MetadataWorkUnit]:
    return [
        wu
        for wu in wus
        if wu.metadata.aspectName == "upstreamLineage"
        and getattr(wu.metadata, "changeType", None) == "PATCH"
    ]


def _patch_ops(wu: MetadataWorkUnit) -> list[dict[str, Any]]:
    return json.loads(wu.metadata.aspect.value.decode("utf-8"))


@pytest.fixture(scope="module")
def empty_config_dump_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Пустой, но валидный ConfigDumpInfo.xml — нужен только pydantic-валидатору.

    Module-scope, чтобы файл создавался один раз на весь модуль и его не
    надо было передавать в каждый тест явно (см. ``_build_source``).
    """
    p = tmp_path_factory.mktemp("uuid") / "ConfigDumpInfo.xml"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
        "<ConfigVersions/>"
        "</ConfigDumpInfo>",
        encoding="utf-8",
    )
    return p


@pytest.fixture(autouse=True)
def _set_empty_config_dump_path(empty_config_dump_path: Path) -> None:
    global _EMPTY_CONFIG_DUMP_PATH
    _EMPTY_CONFIG_DUMP_PATH = empty_config_dump_path


_EMPTY_CONFIG_DUMP_PATH: Path | None = None


def _dataset_name_in(urn: str | None) -> str | None:
    """Достать сегмент ``name`` из dataset-URN или ``None``, если URN не dataset.

    Формат URN: ``urn:li:dataset:(urn:li:dataPlatform:<platform>,<name>,<env>)``.
    Helper удобен для assertion'ов «датасет с именем X есть в выдаче?»,
    т.к. URN с UUID-форматом плохо читается через ``in``-проверки.

    Возвращает ``None`` для всех нон-dataset URN-ов (контейнеров, схем
    и т.п.), чтобы функцию можно было применять к произвольной коллекции
    workunit-URN без отдельного фильтра по типу сущности.
    """
    if not urn or not urn.startswith("urn:li:dataset:("):
        return None
    inner = urn[len("urn:li:dataset:(") :].rsplit(")", 1)[0]
    parts = inner.split(",")
    if len(parts) < 2:
        return None
    return parts[1]


def _is_main_dataset(
    urn: str | None,
    object_uuid: str,
    *,
    infobase_name: str = _INFOBASE_NAME,
) -> bool:
    """True если URN — это dataset основного объекта (не его ТЧ)."""
    return _dataset_name_in(urn) == f"{infobase_name}.{object_uuid}"


def _main_dataset_urn(
    object_uuid: str,
    *,
    infobase_name: str = _INFOBASE_NAME,
    env: str = "PROD",
) -> str:
    return (
        "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,"
        f"{infobase_name}.{object_uuid},{env})"
    )


def _is_tabular_section_dataset(
    urn: str | None,
    object_uuid: str,
    ts_uuid: str,
) -> bool:
    """True если URN — это dataset табличной части `<obj>.<ts>`."""
    return _dataset_name_in(urn) == f"{_INFOBASE_NAME}.{object_uuid}.{ts_uuid}"


def _build_source(
    httpserver: HTTPServer,
    *,
    metadata_uuid_index: MetadataUuidIndex | None = None,
    expect_empty_lineage: bool = True,
    current_upstream_lineage_by_urn: dict[str, UpstreamLineageClass | None] | None = None,
    pipeline_name: str | None = None,
    **config_overrides: Any,
) -> OneCSource:
    assert _EMPTY_CONFIG_DUMP_PATH is not None, (
        "_build_source must be called within a test function so the autouse "
        "fixture _set_empty_config_dump_path has prepared the path."
    )
    config_dict: dict[str, Any] = {
        "base_url": httpserver.url_for(""),
        "username": "u",
        "password": "p",
        "infobase": {"name": _INFOBASE_NAME},
        "metadata_uuid_source": {"config_dump_info_path": str(_EMPTY_CONFIG_DUMP_PATH)},
    }
    config_dict.update(config_overrides)
    config = OneCSourceConfig(**config_dict)
    ctx = PipelineContext(
        run_id="test",
        graph=_FakeGraph(current_upstream_lineage_by_urn),
        pipeline_name=pipeline_name,
    )
    if expect_empty_lineage:
        httpserver.expect_request("/lineage").respond_with_json([])
    return OneCSource(
        config,
        ctx,
        metadata_uuid_index=metadata_uuid_index or _build_uuid_index(),
    )


def _minimal_detail(object_type: str, name: str, full_name: str, **extra: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "object_type": object_type,
        "name": name,
        "full_name": full_name,
        "attributes": [],
    }
    d.update(extra)
    return d


def _setup_three_objects(httpserver: HTTPServer) -> None:
    """Два документа (один с ТЧ, один без) и один справочник без ТЧ."""
    httpserver.expect_request("/objects").respond_with_json(
        [
            {
                "object_type": "Documents",
                "name": "ПоступлениеТоваров",
                "full_name": "Document.ПоступлениеТоваров",
                "synonym": "Поступление товаров",
            },
            {
                "object_type": "Documents",
                "name": "ПростойДокумент",
                "full_name": "Document.ПростойДокумент",
            },
            {
                "object_type": "Catalogs",
                "name": "Номенклатура",
                "full_name": "Catalog.Номенклатура",
            },
        ]
    )
    httpserver.expect_request(
        "/objects/Documents/ПоступлениеТоваров",
    ).respond_with_json(
        _minimal_detail(
            "Documents",
            "ПоступлениеТоваров",
            "Document.ПоступлениеТоваров",
            synonym="Поступление товаров",
        )
    )
    httpserver.expect_request(
        "/objects/Documents/ПростойДокумент",
    ).respond_with_json(
        _minimal_detail(
            "Documents",
            "ПростойДокумент",
            "Document.ПростойДокумент",
        )
    )
    httpserver.expect_request(
        "/objects/Catalogs/Номенклатура",
    ).respond_with_json(
        _minimal_detail(
            "Catalogs",
            "Номенклатура",
            "Catalog.Номенклатура",
        )
    )
    httpserver.expect_request(
        "/objects/Documents/ПоступлениеТоваров/tabular-parts",
    ).respond_with_json([{"name": "Состав", "attributes": []}])
    httpserver.expect_request(
        "/objects/Documents/ПростойДокумент/tabular-parts",
    ).respond_with_json([])
    httpserver.expect_request(
        "/objects/Catalogs/Номенклатура/tabular-parts",
    ).respond_with_json([])


def _setup_postuplenie_db_mapping(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/db-mapping/Documents/ПоступлениеТоваров").respond_with_json(
        {
            "object_type": "Documents",
            "name": "ПоступлениеТоваров",
            "tables": [
                {
                    "db_table_name": "_Document111",
                    "purpose": "Main",
                    "columns": [
                        {
                            "attribute_name": "Номер",
                            "db_columns": [{"column_name": "_Number"}],
                        },
                    ],
                },
            ],
        }
    )


def _collect_wus(src: OneCSource):
    return list(src.get_workunits_internal())


def _collect_processed_wus(src: OneCSource) -> list[MetadataWorkUnit]:
    return list(src.get_workunits())


def _close_and_commit_checkpoints(src: OneCSource) -> None:
    src.close()
    for _, committable in src.ctx.get_committables():
        committable.commit()


class TestHappyPath:
    def test_first_workunit_is_platform(self, httpserver: HTTPServer) -> None:
        _setup_three_objects(httpserver)
        wus = _collect_wus(_build_source(httpserver))
        assert wus[0].metadata.entityUrn == "urn:li:dataPlatform:1c-enterprise"

    def test_dataset_urns_use_uuid_and_are_present(self, httpserver: HTTPServer) -> None:
        """URN dataset/контейнеров строятся на infobase + UUID объекта.

        Проверяем инвариант: имя dataset'а не зависит от транслитерации и
        человекочитаемого имени объекта.
        """
        _setup_three_objects(httpserver)
        urns = {wu.metadata.entityUrn for wu in _collect_wus(_build_source(httpserver))}
        ds_urns = [u for u in urns if u is not None and u.startswith("urn:li:dataset:")]
        assert any(_is_main_dataset(u, _doc_uuid("ПоступлениеТоваров")) for u in ds_urns)
        assert any(_is_main_dataset(u, _cat_uuid("Номенклатура")) for u in ds_urns)
        # В URN не должно остаться ни транслита, ни ENG-префикса вида.
        for u in ds_urns:
            assert "Document." not in u
            assert "Catalog." not in u
            assert "PostuplenieTovarov" not in u
            assert "Nomenklatura" not in u
        # Контейнеры: 1 infobase + 2 type-folder (Documents, Catalogs)
        # + 1 object-container (ПоступлениеТоваров, у которого есть ТЧ).
        containers = [u for u in urns if u is not None and u.startswith("urn:li:container:")]
        assert len(containers) == 4

    def test_custom_infobase_namespaces_urns_and_browse(
        self,
        httpserver: HTTPServer,
    ) -> None:
        _setup_three_objects(httpserver)
        src = _build_source(
            httpserver,
            infobase={"name": "erp-prod", "display_name": "ERP Production"},
        )
        wus = _collect_wus(src)
        urns = {wu.metadata.entityUrn for wu in wus}

        doc_uuid = _doc_uuid("ПоступлениеТоваров")
        ds_urns = [u for u in urns if u is not None and u.startswith("urn:li:dataset:")]
        assert any(_is_main_dataset(u, doc_uuid, infobase_name="erp-prod") for u in ds_urns)
        assert all(
            not (name := _dataset_name_in(u)) or name.startswith("erp-prod.") for u in ds_urns
        )

        infobase_urn = infobase_container_urn_for(
            infobase_name="erp-prod",
            env="PROD",
        )
        type_folder_urn = type_folder_container_urn_for(
            ObjectKind.DOCUMENT,
            infobase_name="erp-prod",
            env="PROD",
        )

        infobase_props = next(
            wu
            for wu in wus
            if wu.metadata.entityUrn == infobase_urn
            and isinstance(wu.metadata.aspect, ContainerPropertiesClass)
        )
        assert infobase_props.metadata.aspect.name == "ERP Production"  # type: ignore[union-attr]
        assert infobase_props.metadata.aspect.qualifiedName == "erp-prod"  # type: ignore[union-attr]

        type_folder_browse = next(
            wu
            for wu in wus
            if wu.metadata.entityUrn == type_folder_urn
            and isinstance(wu.metadata.aspect, BrowsePathsV2Class)
        )
        assert [entry.urn for entry in type_folder_browse.metadata.aspect.path] == [  # type: ignore[union-attr]
            infobase_urn,
        ]

        object_properties = next(
            wu
            for wu in wus
            if wu.metadata.entityUrn is not None
            and _is_main_dataset(wu.metadata.entityUrn, doc_uuid, infobase_name="erp-prod")
            and wu.metadata.aspectName == ONE_C_OBJECT_PROPERTIES
        )
        payload = json.loads(object_properties.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload["configurationName"] == "erp-prod"

    def test_report_counters(self, httpserver: HTTPServer) -> None:
        _setup_three_objects(httpserver)
        src = _build_source(httpserver)
        _ = _collect_wus(src)
        assert src.report.objects_fetched == 3
        assert src.report.objects_emitted == 3
        assert src.report.infobases_emitted == 1
        assert src.report.containers_emitted == 1
        # 2 вида объектов в тестовом наборе: Documents, Catalogs.
        assert src.report.type_folders_emitted == 2
        assert src.report.tabular_parts_emitted == 1  # Состав
        assert src.report.schema_metadata_emitted == 3  # на каждом главном датасете
        assert src.report.objects_filtered == 0

    def test_stateful_cleanup_ownership_filter(self, httpserver: HTTPServer) -> None:
        src = _build_source(httpserver, expect_empty_lineage=False)
        doc_uuid = _doc_uuid("ПоступлениеТоваров")
        doc_dataset_urn = _main_dataset_urn(doc_uuid)
        doc_container_urn = (
            f"urn:li:container:{_INFOBASE_NAME}:{doc_uuid}:PROD"
        )
        posting_flow_urn = f"urn:li:dataFlow:(1c-enterprise,{_INFOBASE_NAME}.posting.{doc_uuid},PROD)"
        posting_job_urn = f"urn:li:dataJob:({posting_flow_urn},posting)"

        assert src._is_stateful_cleanup_owned_urn(doc_dataset_urn)
        assert src._is_stateful_cleanup_owned_urn(
            infobase_container_urn_for(infobase_name=_INFOBASE_NAME, env="PROD")
        )
        assert src._is_stateful_cleanup_owned_urn(
            type_folder_container_urn_for(
                ObjectKind.DOCUMENT,
                infobase_name=_INFOBASE_NAME,
                env="PROD",
            )
        )
        assert src._is_stateful_cleanup_owned_urn(doc_container_urn)
        assert src._is_stateful_cleanup_owned_urn(posting_flow_urn)
        assert src._is_stateful_cleanup_owned_urn(posting_job_urn)

        assert not src._is_stateful_cleanup_owned_urn(
            "urn:li:dataset:(urn:li:dataPlatform:postgres,1c-test.public._document111,PROD)"
        )
        assert not src._is_stateful_cleanup_owned_urn(
            doc_dataset_urn.replace(",PROD)", ",QA)")
        )
        assert not src._is_stateful_cleanup_owned_urn(
            doc_dataset_urn.replace(f"{_INFOBASE_NAME}.", "other-base.")
        )

    def test_stateful_cleanup_soft_deletes_only_onec_owned_entities(
        self,
        httpserver: HTTPServer,
        tmp_path: Path,
    ) -> None:
        """Stateful cleanup не должен брать под управление PG datasets."""
        checkpoint_file = tmp_path / "checkpoint.json"
        stateful_ingestion = {
            "enabled": True,
            "remove_stale_metadata": True,
            # В тесте специально удаляем большую долю 1С-сущностей.
            "fail_safe_threshold": 100.0,
            "state_provider": {
                "type": "file",
                "config": {"filename": str(checkpoint_file)},
            },
        }

        _setup_three_objects(httpserver)
        _setup_postuplenie_db_mapping(httpserver)
        first_src = _build_source(
            httpserver,
            pipeline_name="test-onec-stateful-cleanup",
            stateful_ingestion=stateful_ingestion,
            ingestion={"db_mapping": True},
        )
        first_wus = _collect_processed_wus(first_src)
        assert any(
            wu.metadata.entityUrn
            and wu.metadata.entityUrn.startswith("urn:li:dataset:(urn:li:dataPlatform:postgres,")
            for wu in first_wus
        )
        assert {str(job_id) for job_id in first_src.state_provider._usecase_handlers} == {
            "1c-enterprise_stale_entity_removal_1c-test_PROD",
        }
        _close_and_commit_checkpoints(first_src)

        httpserver.clear()
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ПоступлениеТоваров",
                    "full_name": "Document.ПоступлениеТоваров",
                    "synonym": "Поступление товаров",
                },
            ]
        )
        httpserver.expect_request(
            "/objects/Documents/ПоступлениеТоваров",
        ).respond_with_json(
            _minimal_detail(
                "Documents",
                "ПоступлениеТоваров",
                "Document.ПоступлениеТоваров",
                synonym="Поступление товаров",
            )
        )
        httpserver.expect_request(
            "/objects/Documents/ПоступлениеТоваров/tabular-parts",
        ).respond_with_json([{"name": "Состав", "attributes": []}])
        httpserver.expect_request("/lineage").respond_with_json([])

        second_src = _build_source(
            httpserver,
            pipeline_name="test-onec-stateful-cleanup",
            stateful_ingestion=stateful_ingestion,
            # DB mapping intentionally disappears from the second run. If PG
            # datasets accidentally got into 1C cleanup state, this would emit
            # Status.removed=True for urn:li:dataPlatform:postgres.
            ingestion={"db_mapping": False},
        )
        second_wus = _collect_processed_wus(second_src)

        removed_urns = {
            wu.metadata.entityUrn
            for wu in second_wus
            if isinstance(wu.metadata.aspect, StatusClass)
            and wu.metadata.aspect.removed is True
        }
        assert any(_is_main_dataset(urn, _doc_uuid("ПростойДокумент")) for urn in removed_urns)
        assert any(_is_main_dataset(urn, _cat_uuid("Номенклатура")) for urn in removed_urns)
        assert all(
            not (
                urn
                and urn.startswith("urn:li:dataset:(urn:li:dataPlatform:postgres,")
            )
            for urn in removed_urns
        )
        assert second_src.report.soft_deleted_stale_entities
        _close_and_commit_checkpoints(second_src)

    def test_missing_object_uuid_is_fail_fast(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "НетВДампе",
                    "full_name": "Document.НетВДампе",
                },
            ]
        )
        src = _build_source(httpserver, expect_empty_lineage=False)

        with pytest.raises(ValueError, match="object UUID not found in ConfigDumpInfo.xml"):
            next(src.get_workunits_internal())

        assert src.report.objects_skipped_missing_uuid == 1
        assert src.report.infobases_emitted == 0
        assert src.report.objects_emitted == 0

    def test_missing_tabular_section_uuid_is_fail_fast(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ПоступлениеТоваров",
                    "full_name": "Document.ПоступлениеТоваров",
                },
            ]
        )
        httpserver.expect_request(
            "/objects/Documents/ПоступлениеТоваров/tabular-parts",
        ).respond_with_json([{"name": "НоваяТЧ", "attributes": []}])
        uuid_index = _build_uuid_index()
        uuid_index.tabular_sections.clear()
        src = _build_source(
            httpserver,
            metadata_uuid_index=uuid_index,
            expect_empty_lineage=False,
        )

        with pytest.raises(
            ValueError,
            match="tabular section UUID not found in ConfigDumpInfo.xml",
        ):
            next(src.get_workunits_internal())

        assert src.report.tabular_parts_skipped_missing_uuid == 1
        assert src.report.infobases_emitted == 0
        assert src.report.objects_emitted == 0
        assert src.report.tabular_parts_emitted == 0
        assert src.report.type_folders_emitted == 0

    def test_register_movement_emitted_as_posting_process(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
                {
                    "object_type": "AccumulationRegisters",
                    "name": "ОстаткиТоваров",
                    "full_name": "AccumulationRegister.ОстаткиТоваров",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([{"name": "Товары", "attributes": []}])
        httpserver.expect_request(
            "/objects/AccumulationRegisters/ОстаткиТоваров",
        ).respond_with_json(
            _minimal_detail(
                "AccumulationRegisters",
                "ОстаткиТоваров",
                "AccumulationRegister.ОстаткиТоваров",
            )
        )
        httpserver.expect_request(
            "/lineage",
            query_string={
                "objects": "Document.ЗаказКлиента,AccumulationRegister.ОстаткиТоваров",
                "kinds": "basis,register_movement,manual_dataset_flow",
            },
        ).respond_with_json(
            [
                {
                    "upstream_object_type": "Documents",
                    "upstream_name": "ЗаказКлиента",
                    "downstream_object_type": "AccumulationRegisters",
                    "downstream_name": "ОстаткиТоваров",
                    "kind": "register_movement",
                    "source": "metadata",
                    "confidence": "medium",
                },
                {
                    "upstream_object_type": "Documents",
                    "upstream_name": "ЗаказКлиента",
                    "downstream_object_type": "AccumulationRegisters",
                    "downstream_name": "ОстаткиТоваров",
                    "kind": "selection_criterion",
                },
            ]
        )

        src = _build_source(httpserver)
        wus = _collect_wus(src)

        assert _upstream_patch_wus(wus) == []

        flow_wus = [wu for wu in wus if isinstance(wu.metadata.aspect, DataFlowInfoClass)]
        job_wus = [wu for wu in wus if isinstance(wu.metadata.aspect, DataJobInfoClass)]
        io_wus = [wu for wu in wus if isinstance(wu.metadata.aspect, DataJobInputOutputClass)]
        assert len(flow_wus) == 1
        assert len(job_wus) == 1
        assert len(io_wus) == 1

        flow = flow_wus[0].metadata.aspect
        assert flow.name == "Проведение Документ.ЗаказКлиента"
        assert flow.customProperties["metadataUuid"] == _doc_uuid("ЗаказКлиента")

        job = job_wus[0].metadata.aspect
        assert job.name == "Проведение Документ.ЗаказКлиента"
        assert job.flowUrn == flow_wus[0].metadata.entityUrn

        io = io_wus[0].metadata.aspect
        assert len(io.inputDatasetEdges) == 2
        assert _is_main_dataset(io.inputDatasetEdges[0].destinationUrn, _doc_uuid("ЗаказКлиента"))
        assert io.inputDatasetEdges[0].properties["role"] == "document_main"
        assert _is_tabular_section_dataset(
            io.inputDatasetEdges[1].destinationUrn,
            _doc_uuid("ЗаказКлиента"),
            _ts_uuid("ЗаказКлиента", "Товары"),
        )
        assert io.inputDatasetEdges[1].properties["role"] == "tabular_part"
        assert io.inputDatasetEdges[1].properties["inputSelection"] == "all_tabular_parts"
        assert len(io.outputDatasetEdges) == 1
        assert _is_main_dataset(
            io.outputDatasetEdges[0].destinationUrn,
            _OBJECT_UUIDS[(ObjectKind.ACCUMULATION_REGISTER, "ОстаткиТоваров")],
        )
        assert io.outputDatasetEdges[0].properties["lineageKind"] == "register_movement"
        assert src.report.lineage_edges_fetched == 2
        assert src.report.lineage_edges_emitted == 1
        assert src.report.lineage_processes_emitted == 1
        assert src.report.lineage_process_input_edges_emitted == 2
        assert src.report.lineage_process_output_edges_emitted == 1
        assert src.report.lineage_edges_skipped_unsupported_kind == 1

    def test_manual_dataset_flow_emitted_as_direct_upstream_lineage(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Catalogs",
                    "name": "Номенклатура",
                    "full_name": "Catalog.Номенклатура",
                },
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Catalogs/Номенклатура").respond_with_json(
            _minimal_detail("Catalogs", "Номенклатура", "Catalog.Номенклатура"),
        )
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/lineage",
            query_string={
                "objects": "Catalog.Номенклатура,Document.ЗаказКлиента",
                "kinds": "basis,register_movement,manual_dataset_flow",
            },
        ).respond_with_json(
            [
                {
                    "upstream_object_type": "Catalogs",
                    "upstream_name": "Номенклатура",
                    "downstream_object_type": "Documents",
                    "downstream_name": "ЗаказКлиента",
                    "kind": "manual_dataset_flow",
                    "source": "manual",
                    "confidence": "high",
                    "description": "Ручная связь.",
                    "details": {"origin": "extension_registry"},
                },
            ]
        )

        src = _build_source(httpserver)
        wus = _collect_wus(src)

        upstream_wus = _upstream_patch_wus(wus)
        assert len(upstream_wus) == 1
        ops = _patch_ops(upstream_wus[0])
        assert len(ops) == 1
        assert ops[0]["op"] == "add"
        upstream = ops[0]["value"]
        assert _is_main_dataset(
            upstream["dataset"],
            _OBJECT_UUIDS[(ObjectKind.CATALOG, "Номенклатура")],
        )
        assert upstream["properties"] == {
            ONEC_LINEAGE_MANAGED_BY_PROPERTY: ONEC_LINEAGE_MANAGED_BY_VALUE,
            ONEC_LINEAGE_SCOPE_PROPERTY: ONEC_DIRECT_LINEAGE_SCOPE,
            "lineageKinds": "manual_dataset_flow",
            "sources": "manual",
            "confidences": "high",
            "descriptions": "Ручная связь.",
            "origins": "extension_registry",
        }
        assert [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, DataJobInputOutputClass)
            and (wu.metadata.aspect.inputDatasets or wu.metadata.aspect.outputDatasets)
        ] == []
        assert src.report.lineage_processes_removed == 1
        assert src.report.lineage_edges_emitted == 1
        assert src.report.lineage_edges_skipped_unsupported_kind == 0

    def test_lineage_kinds_filter_emits_only_basis(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Catalogs",
                    "name": "Номенклатура",
                    "full_name": "Catalog.Номенклатура",
                },
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Catalogs/Номенклатура").respond_with_json(
            _minimal_detail("Catalogs", "Номенклатура", "Catalog.Номенклатура"),
        )
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/lineage",
            query_string={
                "objects": "Catalog.Номенклатура,Document.ЗаказКлиента",
                "kinds": "basis",
            },
        ).respond_with_json(
            [
                {
                    "upstream_object_type": "Catalogs",
                    "upstream_name": "Номенклатура",
                    "downstream_object_type": "Documents",
                    "downstream_name": "ЗаказКлиента",
                    "kind": "basis",
                },
            ]
        )

        src = _build_source(
            httpserver,
            ingestion={"lineage_kinds": ["basis"]},
            expect_empty_lineage=False,
        )
        wus = _collect_wus(src)

        upstream_wus = _upstream_patch_wus(wus)
        assert len(upstream_wus) == 1
        upstream = _patch_ops(upstream_wus[0])[0]["value"]
        assert upstream["properties"]["lineageKinds"] == "basis"
        assert [wu for wu in wus if isinstance(wu.metadata.aspect, DataJobInfoClass)] == []
        assert [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, DataJobInputOutputClass)
            and wu.metadata.entityUrn
            and "posting" in wu.metadata.entityUrn
            and wu.metadata.aspect.inputDatasets
        ] == []
        assert src.report.lineage_edges_fetched == 1
        assert src.report.lineage_edges_emitted == 1
        assert src.report.lineage_processes_removed == 1

    def test_lineage_kinds_filter_emits_only_register_movement(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
                {
                    "object_type": "AccumulationRegisters",
                    "name": "ОстаткиТоваров",
                    "full_name": "AccumulationRegister.ОстаткиТоваров",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/objects/AccumulationRegisters/ОстаткиТоваров",
        ).respond_with_json(
            _minimal_detail(
                "AccumulationRegisters",
                "ОстаткиТоваров",
                "AccumulationRegister.ОстаткиТоваров",
            )
        )
        httpserver.expect_request(
            "/lineage",
            query_string={
                "objects": "Document.ЗаказКлиента,AccumulationRegister.ОстаткиТоваров",
                "kinds": "register_movement",
            },
        ).respond_with_json(
            [
                {
                    "upstream_object_type": "Documents",
                    "upstream_name": "ЗаказКлиента",
                    "downstream_object_type": "AccumulationRegisters",
                    "downstream_name": "ОстаткиТоваров",
                    "kind": "register_movement",
                },
            ]
        )

        src = _build_source(
            httpserver,
            ingestion={"lineage_kinds": ["register_movement"]},
            expect_empty_lineage=False,
        )
        wus = _collect_wus(src)

        assert _upstream_patch_wus(wus) == []
        assert [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, DataJobInputOutputClass)
            and wu.metadata.aspect.outputDatasets
        ]
        assert src.report.lineage_edges_fetched == 1
        assert src.report.lineage_edges_emitted == 1
        assert src.report.lineage_processes_emitted == 1
        assert src.report.lineage_processes_removed == 0

    def test_register_movement_removes_stale_process_when_edges_disappear(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/lineage",
            query_string={
                "objects": "Document.ЗаказКлиента",
                "kinds": "basis,register_movement,manual_dataset_flow",
            },
        ).respond_with_json([])

        src = _build_source(httpserver, expect_empty_lineage=False)
        wus = _collect_wus(src)

        removed_statuses = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, StatusClass)
            and wu.metadata.aspect.removed
            and wu.metadata.entityUrn
            and "posting" in wu.metadata.entityUrn
        ]
        cleared_io = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, DataJobInputOutputClass)
            and wu.metadata.entityUrn
            and "posting" in wu.metadata.entityUrn
            and wu.metadata.aspect.inputDatasets == []
            and wu.metadata.aspect.outputDatasets == []
        ]
        assert len(removed_statuses) == 2
        assert len(cleared_io) == 1
        assert src.report.lineage_edges_fetched == 0
        assert src.report.lineage_processes_emitted == 0
        assert src.report.lineage_processes_removed == 1

    def test_empty_lineage_kinds_clears_owned_lineage_without_api_call(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])

        doc_urn = _main_dataset_urn(_doc_uuid("ЗаказКлиента"))
        cat_urn = _main_dataset_urn(_cat_uuid("Номенклатура"))
        src = _build_source(
            httpserver,
            ingestion={"lineage_kinds": []},
            expect_empty_lineage=False,
            current_upstream_lineage_by_urn={
                doc_urn: UpstreamLineageClass(
                    upstreams=[
                        UpstreamClass(
                            dataset=cat_urn,
                            type=DatasetLineageTypeClass.TRANSFORMED,
                            properties={"lineageKinds": "basis"},
                        ),
                    ]
                ),
            },
        )
        wus = _collect_wus(src)

        upstream_wus = _upstream_patch_wus(wus)
        assert len(upstream_wus) == 1
        assert _patch_ops(upstream_wus[0]) == [
            {"op": "remove", "path": f"/upstreams/{cat_urn}", "value": {}}
        ]
        removed_statuses = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, StatusClass)
            and wu.metadata.aspect.removed
            and wu.metadata.entityUrn
            and "posting" in wu.metadata.entityUrn
        ]
        assert len(removed_statuses) == 2
        assert src.report.lineage_edges_fetched == 0
        assert src.report.lineage_owned_edges_removed == 1
        assert src.report.lineage_processes_removed == 1

    def test_lineage_endpoint_error_fails_ingestion(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/lineage",
            query_string={
                "objects": "Document.ЗаказКлиента",
                "kinds": "basis,register_movement,manual_dataset_flow",
            },
        ).respond_with_data(status=500)

        src = _build_source(httpserver, expect_empty_lineage=False)
        with pytest.raises(requests.HTTPError):
            _collect_wus(src)

    def test_large_lineage_scope_uses_unfiltered_request_and_local_filter(
        self,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(source_module, "LINEAGE_FILTER_QUERY_CHAR_LIMIT", 1)
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
                {
                    "object_type": "AccumulationRegisters",
                    "name": "ОстаткиТоваров",
                    "full_name": "AccumulationRegister.ОстаткиТоваров",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/objects/AccumulationRegisters/ОстаткиТоваров",
        ).respond_with_json(
            _minimal_detail(
                "AccumulationRegisters",
                "ОстаткиТоваров",
                "AccumulationRegister.ОстаткиТоваров",
            )
        )
        httpserver.expect_request(
            "/lineage",
            query_string={"kinds": "basis,register_movement,manual_dataset_flow"},
        ).respond_with_json(
            [
                {
                    "upstream_object_type": "Documents",
                    "upstream_name": "ЗаказКлиента",
                    "downstream_object_type": "AccumulationRegisters",
                    "downstream_name": "ОстаткиТоваров",
                    "kind": "register_movement",
                },
                {
                    "upstream_object_type": "Documents",
                    "upstream_name": "Платёж",
                    "downstream_object_type": "AccumulationRegisters",
                    "downstream_name": "ОстаткиТоваров",
                    "kind": "register_movement",
                },
                {
                    "upstream_object_type": "Reports",
                    "upstream_name": "ВнешнийОтчет",
                    "downstream_object_type": "AccumulationRegisters",
                    "downstream_name": "ОстаткиТоваров",
                    "kind": "register_movement",
                },
            ]
        )

        src = _build_source(httpserver, expect_empty_lineage=False)
        wus = _collect_wus(src)

        io_wus = [wu for wu in wus if isinstance(wu.metadata.aspect, DataJobInputOutputClass)]
        assert len(io_wus) == 1
        assert src.report.lineage_edges_fetched == 1
        assert src.report.lineage_edges_emitted == 1

    def test_direct_lineage_requires_datahub_graph_for_safe_merge(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])

        src = _build_source(httpserver)
        src.ctx.graph = None

        with pytest.raises(ConfigurationError, match="1C direct lineage merge"):
            _collect_wus(src)

    def test_integration_service_emitted_as_dataflow_datajob_without_io(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([{"name": "Товары", "attributes": []}])
        httpserver.expect_request(
            "/integration-services",
            query_string={
                "types": "HTTPServices",
                "services": "HTTPService.OrdersApi",
                "endpoints": "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
            },
        ).respond_with_json(
            [
                {
                    "service_type": "HTTPServices",
                    "name": "OrdersApi",
                    "full_name": "HTTPService.OrdersApi",
                    "root_url": "orders",
                    "endpoints": [
                        {
                            "endpoint_type": "http_method",
                            "name": "Post",
                            "full_name": "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
                            "url_template_name": "Orders",
                            "url_template": "/orders",
                            "method_name": "Post",
                            "http_method": "POST",
                            "handler": "PostOrders",
                            "input_objects": [
                                {
                                    "object_type": "Documents",
                                    "name": "ЗаказКлиента",
                                    "full_name": "Document.ЗаказКлиента",
                                    "source": "manual",
                                    "confidence": "high",
                                },
                            ],
                        },
                    ],
                },
            ]
        )

        src = _build_source(
            httpserver,
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
                },
            },
        )
        wus = _collect_wus(src)

        flow_wus = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, DataFlowInfoClass)
            and wu.metadata.aspect.customProperties.get("processKind") == "http_service"
        ]
        job_wus = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, DataJobInfoClass)
            and wu.metadata.aspect.type == "1C_HTTP_SERVICE_METHOD"
        ]
        io_wus = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, DataJobInputOutputClass)
            and wu.metadata.entityUrn
            and ".integration." in wu.metadata.entityUrn
        ]
        assert len(flow_wus) == 1
        assert flow_wus[0].metadata.aspect.name == "HTTP-сервис OrdersApi"
        assert len(job_wus) == 1
        assert job_wus[0].metadata.aspect.customProperties["httpMethod"] == "POST"
        assert job_wus[0].metadata.aspect.customProperties["internalInputObjectFullNames"] == (
            '["Document.ЗаказКлиента"]'
        )
        assert io_wus == []
        assert src.report.integration_services_fetched == 1
        assert src.report.integration_services_emitted == 1
        assert src.report.integration_endpoints_emitted == 1
        assert src.report.integration_internal_inputs_resolved == 1

    def test_integration_services_endpoint_failure_is_fail_fast(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json([])
        httpserver.expect_request(
            "/integration-services",
            query_string={"types": "HTTPServices"},
        ).respond_with_data(status=500)

        src = _build_source(
            httpserver,
            integration_services={"include_services": {"HTTPServices": []}},
        )

        with pytest.raises(requests.HTTPError):
            _collect_wus(src)

    def test_missing_explicit_integration_service_is_fail_fast(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json([])
        httpserver.expect_request(
            "/integration-services",
            query_string={
                "types": "HTTPServices",
                "services": "HTTPService.OrdersApi",
            },
        ).respond_with_json([])

        src = _build_source(
            httpserver,
            integration_services={
                "include_services": {"HTTPServices": ["OrdersApi"]},
            },
        )

        with pytest.raises(ValueError, match="explicit integration services"):
            _collect_wus(src)

    def test_missing_explicit_integration_endpoint_is_fail_fast(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json([])
        httpserver.expect_request(
            "/integration-services",
            query_string={
                "types": "HTTPServices",
                "services": "HTTPService.OrdersApi",
                "endpoints": "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
            },
        ).respond_with_json(
            [
                {
                    "service_type": "HTTPServices",
                    "name": "OrdersApi",
                    "full_name": "HTTPService.OrdersApi",
                    "endpoints": [],
                },
            ]
        )

        src = _build_source(
            httpserver,
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
                },
            },
        )

        with pytest.raises(ValueError, match="explicit integration service endpoints"):
            _collect_wus(src)

    def test_missing_integration_service_uuid_is_fail_fast(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json([])
        httpserver.expect_request(
            "/integration-services",
            query_string={
                "types": "HTTPServices",
                "services": "HTTPService.UnknownApi",
            },
        ).respond_with_json(
            [
                {
                    "service_type": "HTTPServices",
                    "name": "UnknownApi",
                    "full_name": "HTTPService.UnknownApi",
                    "endpoints": [],
                },
            ]
        )

        src = _build_source(
            httpserver,
            integration_services={
                "include_services": {"HTTPServices": ["UnknownApi"]},
            },
        )

        with pytest.raises(ValueError, match="integration service UUID not found"):
            next(src.get_workunits_internal())

        assert src.report.integration_services_skipped_missing_uuid == 1
        assert src.report.infobases_emitted == 0
        assert src.report.objects_emitted == 0

    def test_container_link_on_parent_and_tabular_part(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Dataset-ContainerClass стоит на каждом 1С-датасете.

        В тестовом наборе 3 dataset'а (ПоступлениеТоваров — parent,
        ПростойДокумент, Номенклатура) плюс 1 ТЧ (Состав) = 4 dataset-а.
        На каждом должен быть ContainerClass: parent с ТЧ → object-container,
        parent без ТЧ → type-folder, ТЧ → object-container.
        """
        _setup_three_objects(httpserver)
        wus = _collect_wus(_build_source(httpserver))
        dataset_container_links = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, ContainerClass)
            and wu.metadata.entityUrn is not None
            and wu.metadata.entityUrn.startswith("urn:li:dataset:")
        ]
        assert len(dataset_container_links) == 4
        entity_urns = {link.metadata.entityUrn for link in dataset_container_links}
        # `entity_urns` содержит ровно один URN на каждый dataset:
        # parent документа с ТЧ, ТЧ, второй документ без ТЧ, справочник.
        doc_uuid = _doc_uuid("ПоступлениеТоваров")
        ts_uuid = _ts_uuid("ПоступлениеТоваров", "Состав")
        assert any(u is not None and _is_main_dataset(u, doc_uuid) for u in entity_urns)
        assert any(
            u is not None and _is_tabular_section_dataset(u, doc_uuid, ts_uuid) for u in entity_urns
        )
        assert any(
            u is not None and _is_main_dataset(u, _doc_uuid("ПростойДокумент")) for u in entity_urns
        )
        assert any(
            u is not None and _is_main_dataset(u, _cat_uuid("Номенклатура")) for u in entity_urns
        )


class TestSchemaMetadata:
    def test_new_supported_object_kinds_emit_schema_and_kind_properties(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Новые виды проходят полный путь: /objects -> schema -> kind properties."""
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Constants",
                    "name": "ВалютаУчёта",
                    "full_name": "Constant.ВалютаУчёта",
                },
                {
                    "object_type": "ChartsOfAccounts",
                    "name": "Управленческий",
                    "full_name": "ChartOfAccounts.Управленческий",
                },
                {
                    "object_type": "ChartsOfCalculationTypes",
                    "name": "Начисления",
                    "full_name": "ChartOfCalculationTypes.Начисления",
                },
                {
                    "object_type": "AccountingRegisters",
                    "name": "Управленческий",
                    "full_name": "AccountingRegister.Управленческий",
                },
                {
                    "object_type": "CalculationRegisters",
                    "name": "Начисления",
                    "full_name": "CalculationRegister.Начисления",
                },
                {
                    "object_type": "Enums",
                    "name": "БазыРаспределенияРасходов",
                    "full_name": "Enum.БазыРаспределенияРасходов",
                },
            ]
        )
        httpserver.expect_request("/objects/Constants/ВалютаУчёта").respond_with_json(
            _minimal_detail(
                "Constants",
                "ВалютаУчёта",
                "Constant.ВалютаУчёта",
                attributes=[
                    {
                        "name": "Value",
                        "synonym": "Значение",
                        "types": [{"name": "Catalog.Валюты", "is_reference": True}],
                        "role": "attribute",
                    },
                ],
            ),
        )
        httpserver.expect_request(
            "/objects/ChartsOfAccounts/Управленческий",
        ).respond_with_json(
            _minimal_detail(
                "ChartsOfAccounts",
                "Управленческий",
                "ChartOfAccounts.Управленческий",
                catalog_properties={"is_hierarchical": True, "code_length": 4},
            ),
        )
        httpserver.expect_request(
            "/objects/ChartsOfAccounts/Управленческий/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/objects/ChartsOfCalculationTypes/Начисления",
        ).respond_with_json(
            _minimal_detail(
                "ChartsOfCalculationTypes",
                "Начисления",
                "ChartOfCalculationTypes.Начисления",
                catalog_properties={"is_hierarchical": False},
            ),
        )
        httpserver.expect_request(
            "/objects/ChartsOfCalculationTypes/Начисления/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/objects/AccountingRegisters/Управленческий",
        ).respond_with_json(
            _minimal_detail(
                "AccountingRegisters",
                "Управленческий",
                "AccountingRegister.Управленческий",
                attributes=[
                    {
                        "name": "Сумма",
                        "types": [{"name": "Число", "is_reference": False}],
                        "role": "resource",
                    },
                ],
                register_properties={"register_kind": "Accounting"},
            ),
        )
        httpserver.expect_request(
            "/objects/CalculationRegisters/Начисления",
        ).respond_with_json(
            _minimal_detail(
                "CalculationRegisters",
                "Начисления",
                "CalculationRegister.Начисления",
                attributes=[
                    {
                        "name": "Сотрудник",
                        "types": [{"name": "Catalog.Сотрудники", "is_reference": True}],
                        "role": "dimension",
                    },
                ],
                register_properties={"register_kind": "Calculation"},
            ),
        )
        httpserver.expect_request(
            "/objects/Enums/БазыРаспределенияРасходов",
        ).respond_with_json(
            _minimal_detail(
                "Enums",
                "БазыРаспределенияРасходов",
                "Enum.БазыРаспределенияРасходов",
            ),
        )
        object_scope = (
            "Constant.ВалютаУчёта,ChartOfAccounts.Управленческий,"
            "ChartOfCalculationTypes.Начисления,AccountingRegister.Управленческий,"
            "CalculationRegister.Начисления,Enum.БазыРаспределенияРасходов"
        )
        httpserver.expect_request(
            "/references",
            query_string={"level": "tables", "objects": object_scope},
        ).respond_with_json([])

        src = _build_source(httpserver, ingestion={"lineage": False})
        wus = _collect_wus(src)

        schemas = [wu for wu in wus if isinstance(wu.metadata.aspect, SchemaMetadataClass)]
        assert len(schemas) == 6
        fields_by_urn = {
            wu.metadata.entityUrn: [f.fieldPath for f in wu.metadata.aspect.fields]
            for wu in schemas
        }
        constant_urn = next(
            urn
            for urn in fields_by_urn
            if _is_main_dataset(urn, _object_uuid(ObjectKind.CONSTANT, "ВалютаУчёта"))
        )
        accounting_urn = next(
            urn
            for urn in fields_by_urn
            if _is_main_dataset(
                urn,
                _object_uuid(ObjectKind.ACCOUNTING_REGISTER, "Управленческий"),
            )
        )
        calculation_urn = next(
            urn
            for urn in fields_by_urn
            if _is_main_dataset(
                urn,
                _object_uuid(ObjectKind.CALCULATION_REGISTER, "Начисления"),
            )
        )
        enum_urn = next(
            urn
            for urn in fields_by_urn
            if _is_main_dataset(
                urn,
                _object_uuid(ObjectKind.ENUMERATION, "БазыРаспределенияРасходов"),
            )
        )
        assert fields_by_urn[constant_urn] == ["Value"]
        assert "AccountDr" in fields_by_urn[accounting_urn]
        assert "AccountCr" in fields_by_urn[accounting_urn]
        assert "Summa" in fields_by_urn[accounting_urn]
        assert "CalculationType" in fields_by_urn[calculation_urn]
        assert "Sotrudnik" in fields_by_urn[calculation_urn]
        assert fields_by_urn[enum_urn] == ["Ref"]

        assert src.report.objects_emitted == 6
        assert src.report.schema_metadata_emitted == 6
        assert src.report.kind_properties_emitted == 4
        assert src.report.containers_emitted == 0

    def test_standard_attrs_emitted_for_catalog(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Catalogs",
                    "name": "Номенклатура",
                    "full_name": "Catalog.Номенклатура",
                },
            ]
        )
        httpserver.expect_request("/objects/Catalogs/Номенклатура").respond_with_json(
            {
                "object_type": "Catalogs",
                "name": "Номенклатура",
                "full_name": "Catalog.Номенклатура",
                "attributes": [
                    {
                        "name": "Артикул",
                        "synonym": "Артикул",
                        "types": [{"name": "Строка", "is_reference": False}],
                        "role": "attribute",
                    }
                ],
            }
        )
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура/tabular-parts",
        ).respond_with_json([])
        src = _build_source(httpserver)
        wus = _collect_wus(src)
        schemas = [wu for wu in wus if isinstance(wu.metadata.aspect, SchemaMetadataClass)]
        assert len(schemas) == 1
        fields = schemas[0].metadata.aspect.fields  # type: ignore[union-attr]
        paths = [f.fieldPath for f in fields]
        assert "Ref" in paths
        assert "Code" in paths
        assert "Description" in paths
        assert "Artikul" in paths

    def test_attributes_disabled_keeps_standard_fields_only(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Catalogs",
                    "name": "Номенклатура",
                    "full_name": "Catalog.Номенклатура",
                },
            ]
        )
        httpserver.expect_request("/objects/Catalogs/Номенклатура").respond_with_json(
            {
                "object_type": "Catalogs",
                "name": "Номенклатура",
                "full_name": "Catalog.Номенклатура",
                "attributes": [
                    {
                        "name": "Артикул",
                        "types": [{"name": "Строка", "is_reference": False}],
                        "role": "attribute",
                    }
                ],
            }
        )
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура/tabular-parts",
        ).respond_with_json([])
        src = _build_source(httpserver, ingestion={"attributes": False})
        wus = _collect_wus(src)
        schemas = [wu for wu in wus if isinstance(wu.metadata.aspect, SchemaMetadataClass)]
        assert len(schemas) == 1
        paths = [f.fieldPath for f in schemas[0].metadata.aspect.fields]  # type: ignore[union-attr]
        assert "Ref" in paths
        assert "Artikul" not in paths

    def test_constant_value_kept_when_attributes_disabled(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Constants",
                    "name": "ВалютаУчёта",
                    "full_name": "Constant.ВалютаУчёта",
                },
            ]
        )
        httpserver.expect_request("/objects/Constants/ВалютаУчёта").respond_with_json(
            _minimal_detail(
                "Constants",
                "ВалютаУчёта",
                "Constant.ВалютаУчёта",
                attributes=[
                    {
                        "name": "Value",
                        "synonym": "Значение",
                        "types": [{"name": "Catalog.Валюты", "is_reference": True}],
                        "role": "attribute",
                    },
                ],
            ),
        )

        src = _build_source(
            httpserver,
            ingestion={"attributes": False, "lineage": False},
        )
        wus = _collect_wus(src)

        schemas = [wu for wu in wus if isinstance(wu.metadata.aspect, SchemaMetadataClass)]
        assert len(schemas) == 1
        assert [f.fieldPath for f in schemas[0].metadata.aspect.fields] == ["Value"]


class TestTabularParts:
    def test_tabular_part_dataset_emitted(self, httpserver: HTTPServer) -> None:
        _setup_three_objects(httpserver)
        wus = _collect_wus(_build_source(httpserver))
        doc_uuid = _doc_uuid("ПоступлениеТоваров")
        ts_uuid = _ts_uuid("ПоступлениеТоваров", "Состав")
        tp_urns = {
            wu.metadata.entityUrn
            for wu in wus
            if wu.metadata.entityUrn is not None
            and _is_tabular_section_dataset(wu.metadata.entityUrn, doc_uuid, ts_uuid)
        }
        assert len(tp_urns) == 1

    def test_tabular_part_has_subtype(self, httpserver: HTTPServer) -> None:
        _setup_three_objects(httpserver)
        wus = _collect_wus(_build_source(httpserver))
        tp_subtypes = [
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, SubTypesClass)
            and wu.metadata.aspect.typeNames == [TABULAR_SECTION_SUB_TYPE]  # type: ignore[union-attr]
        ]
        assert len(tp_subtypes) == 1

    def test_tabular_part_schema_has_fk_to_parent(self, httpserver: HTTPServer) -> None:
        _setup_three_objects(httpserver)
        wus = _collect_wus(_build_source(httpserver))
        doc_uuid = _doc_uuid("ПоступлениеТоваров")
        ts_uuid = _ts_uuid("ПоступлениеТоваров", "Состав")
        tp_schema = next(
            wu
            for wu in wus
            if isinstance(wu.metadata.aspect, SchemaMetadataClass)
            and wu.metadata.entityUrn is not None
            and _is_tabular_section_dataset(wu.metadata.entityUrn, doc_uuid, ts_uuid)
        )
        aspect = tp_schema.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        assert aspect.foreignKeys is not None and len(aspect.foreignKeys) == 1
        fk = aspect.foreignKeys[0]
        # Parent FK ссылается на dataset родителя (имя = pure UUID объекта).
        assert _is_main_dataset(fk.foreignDataset, doc_uuid)

    def test_has_tabular_part_relationship_on_parent(self, httpserver: HTTPServer) -> None:
        _setup_three_objects(httpserver)
        wus = _collect_wus(_build_source(httpserver))
        doc_uuid = _doc_uuid("ПоступлениеТоваров")
        ts_uuid = _ts_uuid("ПоступлениеТоваров", "Состав")
        rels = [
            wu
            for wu in wus
            if wu.metadata.aspectName == ONE_C_DOMAIN_RELATIONSHIPS
            and wu.metadata.entityUrn is not None
            and _is_main_dataset(wu.metadata.entityUrn, doc_uuid)
        ]
        assert len(rels) == 1
        payload = json.loads(rels[0].metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert REL_HAS_TABULAR_PART in payload
        # Партнёр в связи — UUID-URN ТЧ (`<doc_uuid>.<ts_uuid>`).
        assert any(
            _is_tabular_section_dataset(u, doc_uuid, ts_uuid) for u in payload[REL_HAS_TABULAR_PART]
        )

    def test_is_tabular_part_of_on_tp(self, httpserver: HTTPServer) -> None:
        _setup_three_objects(httpserver)
        wus = _collect_wus(_build_source(httpserver))
        doc_uuid = _doc_uuid("ПоступлениеТоваров")
        ts_uuid = _ts_uuid("ПоступлениеТоваров", "Состав")
        rels = [
            wu
            for wu in wus
            if wu.metadata.aspectName == ONE_C_DOMAIN_RELATIONSHIPS
            and wu.metadata.entityUrn is not None
            and _is_tabular_section_dataset(wu.metadata.entityUrn, doc_uuid, ts_uuid)
        ]
        assert len(rels) == 1
        payload = json.loads(rels[0].metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert REL_IS_TABULAR_PART_OF in payload

    def test_reference_relationships_for_object_and_tabular_part(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
                {
                    "object_type": "Catalogs",
                    "name": "Номенклатура",
                    "full_name": "Catalog.Номенклатура",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента"),
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([{"name": "Товары", "attributes": []}])
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура",
        ).respond_with_json(
            _minimal_detail(
                "Catalogs",
                "Номенклатура",
                "Catalog.Номенклатура",
            )
        )
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request(
            "/references",
            query_string={
                "level": "tables",
                "objects": "Document.ЗаказКлиента,Catalog.Номенклатура",
            },
        ).respond_with_json(
            [
                {
                    "source_object_type": "Documents",
                    "source_name": "ЗаказКлиента",
                    "target_object_type": "Catalogs",
                    "target_name": "Номенклатура",
                },
                {
                    "source_object_type": "Documents",
                    "source_name": "ЗаказКлиента",
                    "source_tabular_part": "Товары",
                    "target_object_type": "Catalogs",
                    "target_name": "Номенклатура",
                },
            ]
        )

        src = _build_source(httpserver, ingestion={"lineage": False})
        wus = _collect_wus(src)

        doc_uuid = _doc_uuid("ЗаказКлиента")
        tp_uuid = _ts_uuid("ЗаказКлиента", "Товары")
        catalog_uuid = _cat_uuid("Номенклатура")
        payload_by_urn = {
            wu.metadata.entityUrn: json.loads(
                wu.metadata.aspect.value.decode("ascii")  # type: ignore[union-attr]
            )
            for wu in wus
            if wu.metadata.aspectName == ONE_C_DOMAIN_RELATIONSHIPS
        }
        parent_urn = next(u for u in payload_by_urn if _is_main_dataset(u, doc_uuid))
        tp_urn = next(
            u for u in payload_by_urn if _is_tabular_section_dataset(u, doc_uuid, tp_uuid)
        )
        catalog_urn = next(u for u in payload_by_urn if _is_main_dataset(u, catalog_uuid))

        assert REL_HAS_TABULAR_PART in payload_by_urn[parent_urn]
        assert payload_by_urn[parent_urn][REL_REFERS_TO_OBJECT] == [catalog_urn]
        assert payload_by_urn[tp_urn][REL_IS_TABULAR_PART_OF] == [parent_urn]
        assert payload_by_urn[tp_urn][REL_REFERS_TO_OBJECT] == [catalog_urn]
        assert sorted(payload_by_urn[catalog_urn][REL_IS_REFERENCED_BY_OBJECT]) == [
            parent_urn,
            tp_urn,
        ]
        assert src.report.reference_edges_fetched == 2
        assert src.report.reference_edges_emitted == 2
        assert src.report.reference_edges_skipped == 0


class TestKindProperties:
    def test_catalog_properties_emitted(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Catalogs",
                    "name": "Номенклатура",
                    "full_name": "Catalog.Номенклатура",
                },
            ]
        )
        httpserver.expect_request("/objects/Catalogs/Номенклатура").respond_with_json(
            {
                "object_type": "Catalogs",
                "name": "Номенклатура",
                "full_name": "Catalog.Номенклатура",
                "attributes": [],
                "catalog_properties": {"is_hierarchical": True, "code_length": 11},
            }
        )
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура/tabular-parts",
        ).respond_with_json([])
        src = _build_source(httpserver)
        wus = _collect_wus(src)
        aspects = [wu for wu in wus if wu.metadata.aspectName == ONE_C_CATALOG_PROPERTIES]
        assert len(aspects) == 1
        payload = json.loads(aspects[0].metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload == {"isHierarchical": True, "codeLength": 11}

    def test_document_properties_emitted(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {"object_type": "Documents", "name": "Платёж", "full_name": "Document.Платёж"},
            ]
        )
        httpserver.expect_request("/objects/Documents/Платёж").respond_with_json(
            {
                "object_type": "Documents",
                "name": "Платёж",
                "full_name": "Document.Платёж",
                "attributes": [],
                "document_properties": {"is_postable": True},
            }
        )
        httpserver.expect_request(
            "/objects/Documents/Платёж/tabular-parts",
        ).respond_with_json([])
        src = _build_source(httpserver)
        _collect_wus(src)
        assert src.report.kind_properties_emitted == 1

    def test_register_properties_emitted(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "InformationRegisters",
                    "name": "Курсы",
                    "full_name": "InformationRegister.Курсы",
                },
            ]
        )
        httpserver.expect_request("/objects/InformationRegisters/Курсы").respond_with_json(
            {
                "object_type": "InformationRegisters",
                "name": "Курсы",
                "full_name": "InformationRegister.Курсы",
                "attributes": [],
                "register_properties": {"register_kind": "Information", "periodicity": "Day"},
            }
        )
        src = _build_source(httpserver)
        wus = _collect_wus(src)
        aspects = [wu for wu in wus if wu.metadata.aspectName == ONE_C_REGISTER_PROPERTIES]
        assert len(aspects) == 1

    def test_catalog_without_properties_skips_aspect(self, httpserver: HTTPServer) -> None:
        """Если сервис не вернул catalog_properties — aspect не эмитим."""
        _setup_three_objects(httpserver)
        src = _build_source(httpserver)
        wus = _collect_wus(src)
        assert not any(wu.metadata.aspectName == ONE_C_CATALOG_PROPERTIES for wu in wus)
        assert not any(wu.metadata.aspectName == ONE_C_DOCUMENT_PROPERTIES for wu in wus)
        assert not any(wu.metadata.aspectName == ONE_C_REGISTER_PROPERTIES for wu in wus)


class TestFilters:
    def test_include_objects_filters_by_type(self, httpserver: HTTPServer) -> None:
        """include_objects.Catalogs=[] — только справочники в выдаче."""
        httpserver.expect_request(
            "/objects",
            query_string={"types": "Catalogs"},
        ).respond_with_json(
            [
                {
                    "object_type": "Catalogs",
                    "name": "Номенклатура",
                    "full_name": "Catalog.Номенклатура",
                },
            ]
        )
        httpserver.expect_request("/objects/Catalogs/Номенклатура").respond_with_json(
            _minimal_detail("Catalogs", "Номенклатура", "Catalog.Номенклатура")
        )
        httpserver.expect_request(
            "/objects/Catalogs/Номенклатура/tabular-parts",
        ).respond_with_json([])

        src = _build_source(
            httpserver,
            object_filters={"include_objects": {"Catalogs": []}},
        )
        _collect_wus(src)
        assert src.report.objects_emitted == 1

    def test_include_objects_filters_by_name(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(
            "/objects",
            query_string={"types": "Documents"},
        ).respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ПоступлениеТоваров",
                    "full_name": "Document.ПоступлениеТоваров",
                },
                {
                    "object_type": "Documents",
                    "name": "ПростойДокумент",
                    "full_name": "Document.ПростойДокумент",
                },
            ]
        )
        httpserver.expect_request(
            "/objects/Documents/ПоступлениеТоваров",
        ).respond_with_json(
            _minimal_detail(
                "Documents",
                "ПоступлениеТоваров",
                "Document.ПоступлениеТоваров",
            )
        )
        httpserver.expect_request(
            "/objects/Documents/ПоступлениеТоваров/tabular-parts",
        ).respond_with_json([{"name": "Состав", "attributes": []}])
        src = _build_source(
            httpserver,
            object_filters={"include_objects": {"Documents": ["ПоступлениеТоваров"]}},
        )
        _collect_wus(src)
        assert src.report.objects_emitted == 1
        assert src.report.objects_filtered == 1

    def test_common_tabular_section_filter_excludes_noisy_sections(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request(
            "/objects",
            query_string={"types": "Documents"},
        ).respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ПоступлениеТоваров",
                    "full_name": "Document.ПоступлениеТоваров",
                },
                {
                    "object_type": "Documents",
                    "name": "ПростойДокумент",
                    "full_name": "Document.ПростойДокумент",
                },
            ]
        )
        httpserver.expect_request(
            "/objects/Documents/ПоступлениеТоваров",
        ).respond_with_json(
            _minimal_detail(
                "Documents",
                "ПоступлениеТоваров",
                "Document.ПоступлениеТоваров",
            )
        )
        httpserver.expect_request(
            "/objects/Documents/ПоступлениеТоваров/tabular-parts",
        ).respond_with_json([{"name": "Состав", "attributes": []}])
        src = _build_source(
            httpserver,
            object_filters={
                "include_objects": {"Documents": ["ПоступлениеТоваров"]},
                "common_filters": {"tabular_sections": ["Состав"]},
            },
        )
        _collect_wus(src)
        assert src.report.objects_emitted == 1
        assert src.report.objects_filtered == 1
        assert src.report.tabular_parts_emitted == 0
        assert src.report.containers_emitted == 0


class TestTabularPartsToggle:
    def test_tabular_sections_disabled_skips_object_container(self, httpserver: HTTPServer) -> None:
        """При ingestion.tabular_sections=False объектные контейнеры не эмитим.

        Infobase и type-folder при этом эмитятся всегда — они нужны, чтобы
        объекты без ТЧ тоже имели Navigate-иерархию.
        """
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ПоступлениеТоваров",
                    "full_name": "Document.ПоступлениеТоваров",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ПоступлениеТоваров").respond_with_json(
            _minimal_detail("Documents", "ПоступлениеТоваров", "Document.ПоступлениеТоваров")
        )
        src = _build_source(
            httpserver,
            ingestion={"tabular_sections": False},
        )
        wus = _collect_wus(src)
        assert src.report.containers_emitted == 0
        assert src.report.type_folders_emitted == 1
        container_urns = {
            u.metadata.entityUrn
            for u in wus
            if u.metadata.entityUrn is not None
            and u.metadata.entityUrn.startswith("urn:li:container:")
        }
        # Только infobase + type-folder, object-container не появляется.
        assert len(container_urns) == 2

    def test_object_level_tabular_sections_disabled_skips_request(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """per-object ingest_tabular_sections=False не вызывает /tabular-parts."""
        httpserver.expect_request(
            "/objects",
            query_string={"types": "Documents"},
        ).respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ПоступлениеТоваров",
                    "full_name": "Document.ПоступлениеТоваров",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ПоступлениеТоваров").respond_with_json(
            _minimal_detail("Documents", "ПоступлениеТоваров", "Document.ПоступлениеТоваров")
        )
        src = _build_source(
            httpserver,
            object_filters={
                "include_objects": {
                    "Documents": [
                        {
                            "name": "ПоступлениеТоваров",
                            "ingest_tabular_sections": False,
                        },
                    ],
                },
            },
        )
        _collect_wus(src)
        assert src.report.tabular_parts_emitted == 0
        assert src.report.containers_emitted == 0

    def test_registers_never_trigger_tabular_parts_call(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Регистры не имеют ТЧ — source не должен вызывать /tabular-parts."""
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "InformationRegisters",
                    "name": "Курсы",
                    "full_name": "InformationRegister.Курсы",
                },
            ]
        )
        httpserver.expect_request("/objects/InformationRegisters/Курсы").respond_with_json(
            _minimal_detail("InformationRegisters", "Курсы", "InformationRegister.Курсы")
        )
        src = _build_source(httpserver)
        _collect_wus(src)
        assert src.report.containers_emitted == 0


class TestUnknownKinds:
    def test_unknown_kind_skipped_with_warning(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {"object_type": "Микроконтроллеры", "name": "X", "full_name": "Микроконтроллер.X"},
            ]
        )
        src = _build_source(httpserver)
        _collect_wus(src)
        assert src.report.objects_skipped_unknown_kind == 1
        assert src.report.objects_emitted == 0
        assert any("unknown 1C object kind" in w.message for w in src.report.warnings)


class TestDbMapping:
    """Тесты эмиссии PG-слоя из ``/db-mapping``."""

    def _setup_zakaz_with_db_mapping(self, httpserver: HTTPServer) -> None:
        """Один документ ЗаказКлиента с одной ТЧ + Main + ТЧ-таблицей."""
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента")
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json(
            [
                {"name": "Товары", "attributes": []},
            ]
        )
        # Формат /db-mapping: DB-neutral поля и `tabular_section_name`
        # для резолва TabularSection -> 1С-ТЧ.
        httpserver.expect_request("/db-mapping/Documents/ЗаказКлиента").respond_with_json(
            {
                "object_type": "Documents",
                "name": "ЗаказКлиента",
                "tables": [
                    {
                        "db_table_name": "_Document123",
                        "purpose": "Main",
                        "columns": [
                            {
                                "attribute_name": "Номер",
                                "db_columns": [{"column_name": "_Number"}],
                            },
                        ],
                    },
                    {
                        "db_table_name": "_Document123_VT456",
                        "purpose": "TabularSection",
                        "tabular_section_name": "Товары",
                        "columns": [
                            {
                                "attribute_name": "Количество",
                                "db_columns": [{"column_name": "_Fld1"}],
                            },
                        ],
                    },
                ],
            }
        )

    def _setup_register_with_totals(self, httpserver: HTTPServer) -> None:
        """Регистр накопления — Main + Totals (без 1С-двойника для Totals)."""
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "AccumulationRegisters",
                    "name": "ОстаткиТоваров",
                    "full_name": "AccumulationRegister.ОстаткиТоваров",
                },
            ]
        )
        httpserver.expect_request(
            "/objects/AccumulationRegisters/ОстаткиТоваров",
        ).respond_with_json(
            _minimal_detail(
                "AccumulationRegisters",
                "ОстаткиТоваров",
                "AccumulationRegister.ОстаткиТоваров",
            ),
        )
        # Регистры не имеют ТЧ — этот endpoint Source не дёргает,
        # mock не нужен.
        httpserver.expect_request(
            "/db-mapping/AccumulationRegisters/ОстаткиТоваров",
        ).respond_with_json(
            {
                "object_type": "AccumulationRegisters",
                "name": "ОстаткиТоваров",
                "tables": [
                    {"db_table_name": "_AccumRg165", "purpose": "Main", "columns": []},
                    {"db_table_name": "_AccumRgT166", "purpose": "Totals", "columns": []},
                ],
            }
        )

    def _cfg(self) -> dict[str, Any]:
        return {
            "ingestion": {"db_mapping": True},
            "postgres": {"database": "1c-test", "schema": "public"},
        }

    def test_pg_datasets_emitted_for_all_purposes(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """PG-датасет эмитится для каждой таблицы, независимо от purpose."""
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)
        pg_urns = {
            wu.metadata.entityUrn
            for wu in wus
            if wu.metadata.entityUrn is not None
            and "urn:li:dataPlatform:postgres" in wu.metadata.entityUrn
        }
        # Два PG-датасета: Main + TabularSection.
        # URN — lowercase: согласован со стандартным PG-коннектором,
        # PostgreSQL без двойных кавычек хранит идентификаторы lowercase
        # (см. pg_normalize в mapping/urn.py).
        assert len(pg_urns) == 2
        assert any("1c-test.public._document123," in u for u in pg_urns)
        assert any("1c-test.public._document123_vt456" in u for u in pg_urns)
        assert src.report.pg_datasets_emitted == 2
        # Sibling строится для Main и TabularSection.
        assert src.report.db_mappings_emitted == 2
        assert src.report.pg_aux_datasets_emitted == 0

    def test_db_mapping_skips_tabular_sections_excluded_by_object_filters(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """ТЧ, исключённая recipe-фильтром, не должна попадать и в PG allow-scope."""
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(
            httpserver,
            **self._cfg(),
            object_filters={
                "common_filters": {"tabular_sections": ["Товары"]},
            },
        )
        wus = _collect_wus(src)

        pg_urns = {
            wu.metadata.entityUrn
            for wu in wus
            if wu.metadata.entityUrn is not None
            and "urn:li:dataPlatform:postgres" in wu.metadata.entityUrn
        }
        assert len(pg_urns) == 1
        assert any("1c-test.public._document123," in u for u in pg_urns)
        assert src.report.tabular_parts_emitted == 0
        assert src.report.pg_datasets_emitted == 1
        assert src.report.db_mappings_emitted == 1
        assert src.report.pg_aux_datasets_emitted == 0

    def test_table_purpose_in_pg_dataset_custom_properties(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """customProperties.table_purpose проставляется для каждой
        PG-таблицы — нужно, чтобы отличать вспомогательные таблицы
        в UI до подключения стандартного PG-коннектора."""
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)
        pg_props = [
            wu
            for wu in wus
            if wu.metadata.aspectName == "datasetProperties"
            and wu.metadata.entityUrn is not None
            and "urn:li:dataPlatform:postgres" in wu.metadata.entityUrn
        ]
        props_by_table = {
            wu.metadata.aspect.name: dict(wu.metadata.aspect.customProperties) for wu in pg_props
        }
        # display name PG-датасета — lowercase (отражает реальное имя в БД).
        assert props_by_table == {
            "_document123": {"table_purpose": "Main"},
            "_document123_vt456": {
                "table_purpose": "TabularSection",
                # Имя ТЧ доступно и со стороны PG-датасета — полезно,
                # когда смотришь PG напрямую без Sibling-перехода.
                # tabular_section_name — это 1С-семантика (кириллица),
                # lowercase к нему не применяем.
                "tabular_section_name": "Товары",
            },
        }

    def test_siblings_for_main_and_tabular_section(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Sibling строится для Main и TabularSection (с резолвом ТЧ
        через tabular_section_name). Получаем 2 пары = 4 workunit'а."""
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)
        siblings = [wu for wu in wus if isinstance(wu.metadata.aspect, SiblingsClass)]
        # 2 «сиблабельные» таблицы × 2 стороны = 4 workunit'а.
        assert len(siblings) == 4

        onec_primary = [wu for wu in siblings if wu.metadata.aspect.primary is True]
        pg_secondary = [wu for wu in siblings if wu.metadata.aspect.primary is False]
        assert len(onec_primary) == 2
        assert len(pg_secondary) == 2

        # На 1С-стороне сиблятся: главный объект + ТЧ-датасет.
        # Имена datasets — pure UUID объекта/ТЧ.
        zk_uuid = _doc_uuid("ЗаказКлиента")
        tovary_uuid = _ts_uuid("ЗаказКлиента", "Товары")
        onec_urns = {wu.metadata.entityUrn for wu in onec_primary}
        assert any(u is not None and _is_main_dataset(u, zk_uuid) for u in onec_urns), (
            f"main onec dataset not in siblings (onec_urns={onec_urns!r})"
        )
        assert any(
            u is not None and _is_tabular_section_dataset(u, zk_uuid, tovary_uuid)
            for u in onec_urns
        ), f"tabular-section onec dataset not in siblings (onec_urns={onec_urns!r})"

        # PG-сторона: главная таблица сиблится с 1С-объектом,
        # ТЧ-таблица — с 1С-ТЧ-датасетом.
        pairs = {
            (wu.metadata.entityUrn or "").split(",")[1]: wu.metadata.aspect.siblings[0]
            for wu in pg_secondary
        }
        # _document123 ↔ 1С-объект (имя — UUID); _document123_vt456 ↔ ТЧ.
        main_pg = next(k for k in pairs if k == "1c-test.public._document123")
        tp_pg = next(k for k in pairs if "_vt456" in k)
        assert _is_main_dataset(pairs[main_pg], zk_uuid)
        assert _is_tabular_section_dataset(pairs[tp_pg], zk_uuid, tovary_uuid)

    def test_emit_db_siblings_false_keeps_mapping_without_siblings(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Отключение standard Siblings не отключает DB mapping.

        Source всё равно эмитит PG skeleton datasets, oneCDbMapping и
        MapsToDbTable, но не пишет Siblings aspects. Существующие Siblings
        не очищаются автоматически: это whole-aspect UPSERT, который может
        стереть чужие связи на DB-датасете.
        """
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(
            httpserver,
            ingestion={"db_mapping": True, "emit_db_siblings": False},
            postgres={"database": "1c-test", "schema": "public"},
        )
        wus = _collect_wus(src)

        assert src.report.pg_datasets_emitted == 2
        assert src.report.db_mappings_emitted == 2

        siblings = [wu for wu in wus if isinstance(wu.metadata.aspect, SiblingsClass)]
        assert siblings == []

        db_mapping_wus = [wu for wu in wus if wu.metadata.aspectName == ONE_C_DB_MAPPING]
        assert len(db_mapping_wus) == 2

        maps_to = []
        for wu in wus:
            if wu.metadata.aspectName != ONE_C_DOMAIN_RELATIONSHIPS:
                continue
            payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
            if REL_MAPS_TO_DB_TABLE in payload:
                maps_to.append(payload[REL_MAPS_TO_DB_TABLE])
        assert len(maps_to) == 2
        assert all(targets and "postgres" in targets[0] for targets in maps_to)

    def test_one_c_db_mapping_for_main_and_tabular_section(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """oneCDbMapping (custom aspect) эмитится для Main (на главном
        1С-датасете) и для TabularSection (на 1С-датасете ТЧ)."""
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)
        db_mapping_wus = [wu for wu in wus if wu.metadata.aspectName == ONE_C_DB_MAPPING]
        assert len(db_mapping_wus) == 2

        by_pg_table = {
            json.loads(wu.metadata.aspect.value.decode("ascii"))[
                "dbTableName"
            ]:  # type: ignore[union-attr]
            (wu.metadata.entityUrn or "")
            for wu in db_mapping_wus
        }
        # Main-aspect — на главном объекте, ТЧ-aspect — на ТЧ-датасете.
        # dbTableName в oneCDbMapping — lowercase, как имя реальной таблицы PG.
        assert "_document123" in by_pg_table
        assert "_document123_vt456" in by_pg_table
        zk_uuid = _doc_uuid("ЗаказКлиента")
        tovary_uuid = _ts_uuid("ЗаказКлиента", "Товары")
        assert _is_main_dataset(by_pg_table["_document123"], zk_uuid)
        assert _is_tabular_section_dataset(
            by_pg_table["_document123_vt456"],
            zk_uuid,
            tovary_uuid,
        )

    def test_maps_to_db_relationship_for_main_and_tabular_section(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """mapsToDbTable typed-relationship: одна запись на Main и
        одна на TabularSection — как зеркало oneCDbMapping."""
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)
        maps_to = []
        for wu in wus:
            if wu.metadata.aspectName != ONE_C_DOMAIN_RELATIONSHIPS:
                continue
            payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
            if REL_MAPS_TO_DB_TABLE in payload:
                maps_to.append((wu.metadata.entityUrn or "", payload[REL_MAPS_TO_DB_TABLE]))
        assert len(maps_to) == 2

        # Каждая запись имеет ровно одну цель (pg-таблицу).
        for _, targets in maps_to:
            assert len(targets) == 1
            assert "postgres" in targets[0]

        # Маппинг 1С-датасет → его PG-таблица.
        zk_uuid = _doc_uuid("ЗаказКлиента")
        tovary_uuid = _ts_uuid("ЗаказКлиента", "Товары")
        by_onec = {urn: targets[0] for urn, targets in maps_to}
        main_onec = next(u for u in by_onec if _is_main_dataset(u, zk_uuid))
        tp_onec = next(u for u in by_onec if _is_tabular_section_dataset(u, zk_uuid, tovary_uuid))
        assert "_document123," in by_onec[main_onec]
        assert "_vt456" in by_onec[tp_onec]

    def test_tabular_section_without_resolved_tp_falls_back_to_pg_only(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Если tabular_section_name из API не совпадает с известными
        ТЧ (ingestion.tabular_sections=False или несогласованность) —
        Sibling не строится, эмитится только PG-датасет с warning."""
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента")
        )
        # Намеренно ВЫКЛЮЧИЛИ ТЧ — карта tp_urn_by_name будет пустой.
        httpserver.expect_request(
            "/db-mapping/Documents/ЗаказКлиента",
        ).respond_with_json(
            {
                "object_type": "Documents",
                "name": "ЗаказКлиента",
                "tables": [
                    {"db_table_name": "_Document123", "purpose": "Main", "columns": []},
                    {
                        "db_table_name": "_Document123_VT456",
                        "purpose": "TabularSection",
                        "tabular_section_name": "Товары",
                        "columns": [],
                    },
                ],
            }
        )
        src = _build_source(
            httpserver,
            ingestion={"db_mapping": True, "tabular_sections": False},
            postgres={"database": "1c-test", "schema": "public"},
        )
        wus = _collect_wus(src)

        # Оба PG-датасета эмитнуты.
        assert src.report.pg_datasets_emitted == 2
        # Но Sibling-обвязка только для Main: ТЧ-датасета не существует.
        assert src.report.db_mappings_emitted == 1
        assert src.report.pg_aux_datasets_emitted == 1
        siblings = [wu for wu in wus if isinstance(wu.metadata.aspect, SiblingsClass)]
        assert len(siblings) == 2  # только Main × 2 стороны

    def test_register_totals_emits_pg_dataset_without_sibling(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Для регистра: Main → Sibling/aspect; Totals → только PG-датасет.

        У таблиц итогов нет 1С-объекта-аналога (это внутренний слой
        регистра), поэтому Sibling не строим.
        """
        self._setup_register_with_totals(httpserver)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)

        pg_urns = sorted(
            {
                wu.metadata.entityUrn
                for wu in wus
                if wu.metadata.entityUrn is not None
                and "urn:li:dataPlatform:postgres" in wu.metadata.entityUrn
            }
        )
        # Оба PG-датасета (Main + Totals) видны.
        assert len(pg_urns) == 2
        assert src.report.pg_datasets_emitted == 2
        assert src.report.pg_aux_datasets_emitted == 1  # Totals

        # Sibling — только для Main → 2 workunit'а (1С + PG).
        siblings = [wu for wu in wus if isinstance(wu.metadata.aspect, SiblingsClass)]
        assert len(siblings) == 2
        # Totals не должна попасть в Sibling.
        sibling_targets = {tuple(wu.metadata.aspect.siblings) for wu in siblings}
        for targets in sibling_targets:
            for t in targets:
                assert "_accumrgt166" not in t

    def test_empty_db_mapping_does_not_emit_tabular_ui_aspect(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Пустой oneCDbMapping не эмитим: DataHub tabular renderer
        строит колонки по первой строке `attributeColumns`."""
        self._setup_register_with_totals(httpserver)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)

        assert not any(wu.metadata.aspectName == ONE_C_DB_MAPPING for wu in wus)

        # Семантическая связь с PG-таблицей при этом сохраняется.
        maps_to_targets = []
        for wu in wus:
            if wu.metadata.aspectName != ONE_C_DOMAIN_RELATIONSHIPS:
                continue
            payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
            maps_to_targets.extend(payload.get(REL_MAPS_TO_DB_TABLE, []))
        assert any("_accumrg165" in target for target in maps_to_targets)

    def test_unknown_table_purpose_skipped_with_warning(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Forward-compat: незнакомый purpose не валит ingestion."""
        httpserver.expect_request("/objects").respond_with_json(
            [
                {"object_type": "Catalogs", "name": "Foo", "full_name": "Catalog.Foo"},
            ]
        )
        httpserver.expect_request("/objects/Catalogs/Foo").respond_with_json(
            _minimal_detail("Catalogs", "Foo", "Catalog.Foo")
        )
        httpserver.expect_request(
            "/objects/Catalogs/Foo/tabular-parts",
        ).respond_with_json([])
        httpserver.expect_request("/db-mapping/Catalogs/Foo").respond_with_json(
            {
                "object_type": "Catalogs",
                "name": "Foo",
                "tables": [
                    {"db_table_name": "_Reference1", "purpose": "Main", "columns": []},
                    # Гипотетическое будущее назначение — должно быть пропущено.
                    {
                        "db_table_name": "_Reference1_Future",
                        "purpose": "FutureTotals",
                        "columns": [],
                    },
                ],
            }
        )
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)

        pg_urns = {
            wu.metadata.entityUrn
            for wu in wus
            if wu.metadata.entityUrn is not None
            and "urn:li:dataPlatform:postgres" in wu.metadata.entityUrn
        }
        # Эмитнут только Main, незнакомая таблица пропущена.
        # URN — lowercase, см. pg_normalize.
        assert len(pg_urns) == 1
        assert any("_reference1," in u for u in pg_urns)
        assert src.report.db_mapping_unknown_purpose_skipped == 1

    def test_db_mapping_disabled_skips_pg_emission(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """db_mapping=False (default) — /db-mapping не вызывается и PG нет."""
        # Намеренно НЕ регистрируем /db-mapping — если source его всё же
        # позовёт, httpserver вернёт 500 и тест упадёт.
        self._setup_zakaz_with_db_mapping_no_mapping_endpoint(httpserver)
        src = _build_source(httpserver)  # db_mapping=False по умолчанию
        wus = _collect_wus(src)
        pg_any = [
            wu
            for wu in wus
            if wu.metadata.entityUrn is not None
            and "urn:li:dataPlatform:postgres" in wu.metadata.entityUrn
        ]
        assert pg_any == []
        assert src.report.pg_datasets_emitted == 0

    def test_constant_skips_db_mapping_even_when_enabled(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Константа не вызывает /db-mapping: у неё нет 1:1 физ. таблицы."""
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Constants",
                    "name": "ВалютаУчёта",
                    "full_name": "Constant.ВалютаУчёта",
                },
            ]
        )
        httpserver.expect_request("/objects/Constants/ВалютаУчёта").respond_with_json(
            _minimal_detail("Constants", "ВалютаУчёта", "Constant.ВалютаУчёта"),
        )

        src = _build_source(
            httpserver,
            ingestion={"db_mapping": True, "lineage": False},
            postgres={"database": "1c-test", "schema": "public"},
        )
        wus = _collect_wus(src)

        assert not any(
            wu.metadata.entityUrn is not None
            and "urn:li:dataPlatform:postgres" in wu.metadata.entityUrn
            for wu in wus
        )
        assert src.report.pg_datasets_emitted == 0
        assert src.report.db_mappings_emitted == 0
        assert src.report.db_mapping_not_found == 0

    def _setup_zakaz_with_db_mapping_no_mapping_endpoint(
        self,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/objects").respond_with_json(
            [
                {
                    "object_type": "Documents",
                    "name": "ЗаказКлиента",
                    "full_name": "Document.ЗаказКлиента",
                },
            ]
        )
        httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
            _minimal_detail("Documents", "ЗаказКлиента", "Document.ЗаказКлиента")
        )
        httpserver.expect_request(
            "/objects/Documents/ЗаказКлиента/tabular-parts",
        ).respond_with_json([])

    def test_missing_db_mapping_endpoint_warns_does_not_fail(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """Если /db-mapping возвращает 404 — ingest продолжается, warning в report."""
        self._setup_zakaz_with_db_mapping_no_mapping_endpoint(httpserver)
        httpserver.expect_request(
            "/db-mapping/Documents/ЗаказКлиента",
        ).respond_with_data("not found", status=404)
        src = _build_source(httpserver, **self._cfg())
        wus = _collect_wus(src)
        assert src.report.db_mapping_not_found == 1
        # 1С-датасет всё равно эмитнули.
        onec_urns = {
            wu.metadata.entityUrn
            for wu in wus
            if wu.metadata.entityUrn is not None
            and "1c-enterprise" in wu.metadata.entityUrn
            and wu.metadata.entityUrn.startswith("urn:li:dataset:")
        }
        assert any(_is_main_dataset(u, _doc_uuid("ЗаказКлиента")) for u in onec_urns)

    def test_emit_custom_aspects_false_filters_db_mapping_aspects(
        self,
        httpserver: HTTPServer,
    ) -> None:
        """emit_custom_aspects=False глушит oneCDbMapping и mapsToDbTable,
        но PG-датасеты и Siblings (стандартные) всё равно эмитятся."""
        self._setup_zakaz_with_db_mapping(httpserver)
        src = _build_source(
            httpserver,
            ingestion={"db_mapping": True, "emit_custom_aspects": False},
            postgres={"database": "1c-test", "schema": "public"},
        )
        wus = _collect_wus(src)
        # Никаких custom-аспектов в выдаче.
        assert not any(wu.metadata.aspectName == ONE_C_DB_MAPPING for wu in wus)
        # Проверяем конкретный relationship key, а не весь aspect:
        # другие oneCDomainRelationships здесь допустимы.
        for wu in wus:
            if wu.metadata.aspectName == ONE_C_DOMAIN_RELATIONSHIPS:
                payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
                assert REL_MAPS_TO_DB_TABLE not in payload
        # Siblings не фильтруются вместе с custom aspects.
        assert src.report.pg_datasets_emitted == 2
        siblings = [wu for wu in wus if isinstance(wu.metadata.aspect, SiblingsClass)]
        assert len(siblings) == 4  # Main + ТЧ → 2 пары × 2 стороны


class TestCreateFromDict:
    def test_create_parses_recipe(self, httpserver: HTTPServer) -> None:
        # create() сам валидирует config и загружает UUID-индекс из XML.
        assert _EMPTY_CONFIG_DUMP_PATH is not None
        src = OneCSource.create(
            {
                "base_url": httpserver.url_for(""),
                "username": "u",
                "password": "p",
                "env": "DEV",
                "infobase": {"name": _INFOBASE_NAME},
                "metadata_uuid_source": {
                    "config_dump_info_path": str(_EMPTY_CONFIG_DUMP_PATH),
                },
            },
            PipelineContext(run_id="create-test"),
        )
        assert src.config.env == "DEV"
        src.close()

    def test_create_rejects_bad_recipe(self) -> None:
        with pytest.raises(ValidationError):
            OneCSource.create({"base_url": "http://x"}, PipelineContext(run_id="bad"))
