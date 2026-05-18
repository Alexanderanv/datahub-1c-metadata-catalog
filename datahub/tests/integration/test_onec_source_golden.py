from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from datahub.emitter.serialization_helper import pre_json_transform
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import UpstreamLineageClass
from pytest_httpserver import HTTPServer

from datahub_1c.config import OneCSourceConfig
from datahub_1c.mapping.metadata_uuid import MetadataUuidIndex
from datahub_1c.mapping.urn import ObjectKind
from datahub_1c.source import OneCSource

_GOLDEN_PATH = Path(__file__).with_name("one_source_mcp_golden.json")

_OBJECT_UUIDS: dict[tuple[ObjectKind, str], str] = {
    (ObjectKind.DOCUMENT, "ЗаказКлиента"): "11111111-1111-1111-1111-111111111103",
    (ObjectKind.CATALOG, "Номенклатура"): "22222222-2222-2222-2222-222222222201",
    (ObjectKind.ACCUMULATION_REGISTER, "ОстаткиТоваров"): (
        "33333333-3333-3333-3333-333333333302"
    ),
}
_TS_UUIDS: dict[tuple[ObjectKind, str, str], str] = {
    (ObjectKind.DOCUMENT, "ЗаказКлиента", "Товары"): (
        "44444444-4444-4444-4444-444444444402"
    ),
}
_ATTR_UUIDS: dict[tuple[ObjectKind, str, str | None, str], str] = {
    (ObjectKind.CATALOG, "Номенклатура", None, "Артикул"): (
        "55555555-5555-5555-5555-555555555501"
    ),
}
_INFOBASE_NAME = "1c-test"


class _FakeGraph:
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
        return None

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
        return {}


def _uuid_index() -> MetadataUuidIndex:
    return MetadataUuidIndex(
        objects=dict(_OBJECT_UUIDS),
        tabular_sections=dict(_TS_UUIDS),
        attributes=dict(_ATTR_UUIDS),
    )


def _empty_config_dump(tmp_path: Path) -> Path:
    path = tmp_path / "ConfigDumpInfo.xml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
        "<ConfigVersions/>"
        "</ConfigDumpInfo>",
        encoding="utf-8",
    )
    return path


def _build_source(httpserver: HTTPServer, tmp_path: Path) -> OneCSource:
    config = OneCSourceConfig(
        base_url=httpserver.url_for(""),
        username="u",
        password="p",
        infobase={"name": _INFOBASE_NAME},
        metadata_uuid_source={
            "config_dump_info_path": str(_empty_config_dump(tmp_path)),
        },
        ingestion={"db_mapping": True},
        postgres={"database": "1c-test", "schema": "public"},
    )
    return OneCSource(
        config,
        PipelineContext(run_id="golden-test", graph=_FakeGraph()),
        metadata_uuid_index=_uuid_index(),
    )


def _detail(object_type: str, name: str, full_name: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "object_type": object_type,
        "name": name,
        "full_name": full_name,
        "attributes": [],
    }
    payload.update(extra)
    return payload


def _setup_api(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/objects").respond_with_json([
        {
            "object_type": "Documents",
            "name": "ЗаказКлиента",
            "full_name": "Document.ЗаказКлиента",
            "synonym": "Заказ клиента",
        },
        {
            "object_type": "Catalogs",
            "name": "Номенклатура",
            "full_name": "Catalog.Номенклатура",
        },
        {
            "object_type": "AccumulationRegisters",
            "name": "ОстаткиТоваров",
            "full_name": "AccumulationRegister.ОстаткиТоваров",
        },
    ])
    httpserver.expect_request("/objects/Documents/ЗаказКлиента").respond_with_json(
        _detail(
            "Documents",
            "ЗаказКлиента",
            "Document.ЗаказКлиента",
            synonym="Заказ клиента",
            document_properties={"is_postable": True, "number_length": 11},
        ),
    )
    httpserver.expect_request(
        "/objects/Documents/ЗаказКлиента/tabular-parts",
    ).respond_with_json([
        {
            "name": "Товары",
            "attributes": [
                {
                    "name": "Номенклатура",
                    "types": [{"name": "Catalog.Номенклатура", "is_reference": True}],
                    "role": "attribute",
                },
                {
                    "name": "Количество",
                    "types": [{"name": "Число", "is_reference": False}],
                    "role": "attribute",
                },
            ],
        },
    ])
    httpserver.expect_request("/objects/Catalogs/Номенклатура").respond_with_json(
        _detail(
            "Catalogs",
            "Номенклатура",
            "Catalog.Номенклатура",
            attributes=[
                {
                    "name": "Артикул",
                    "types": [{"name": "Строка", "is_reference": False}],
                    "role": "attribute",
                },
            ],
            catalog_properties={"is_hierarchical": True, "owner_names": ["Контрагенты"]},
        ),
    )
    httpserver.expect_request(
        "/objects/Catalogs/Номенклатура/tabular-parts",
    ).respond_with_json([])
    httpserver.expect_request(
        "/objects/AccumulationRegisters/ОстаткиТоваров",
    ).respond_with_json(
        _detail(
            "AccumulationRegisters",
            "ОстаткиТоваров",
            "AccumulationRegister.ОстаткиТоваров",
            register_properties={"register_kind": "Accumulation", "totals_enabled": True},
        ),
    )
    httpserver.expect_request("/db-mapping/Documents/ЗаказКлиента").respond_with_json({
        "object_type": "Documents",
        "name": "ЗаказКлиента",
        "tables": [
            {
                "db_table_name": "_Document164",
                "purpose": "Main",
                "columns": [
                    {
                        "attribute_name": "Номер",
                        "db_columns": [{"column_name": "_Number"}],
                    },
                ],
            },
            {
                "db_table_name": "_Document164_VT51557",
                "purpose": "TabularSection",
                "tabular_section_name": "Товары",
                "columns": [
                    {
                        "attribute_name": "Номенклатура",
                        "db_columns": [{"column_name": "_Fld51558RRef"}],
                    },
                ],
            },
        ],
    })
    httpserver.expect_request("/db-mapping/Catalogs/Номенклатура").respond_with_json({
        "object_type": "Catalogs",
        "name": "Номенклатура",
        "tables": [{"db_table_name": "_Reference42", "purpose": "Main", "columns": []}],
    })
    httpserver.expect_request(
        "/db-mapping/AccumulationRegisters/ОстаткиТоваров",
    ).respond_with_json({
        "object_type": "AccumulationRegisters",
        "name": "ОстаткиТоваров",
        "tables": [
            {"db_table_name": "_AccumRg165", "purpose": "Main", "columns": []},
            {"db_table_name": "_AccumRgT166", "purpose": "Totals", "columns": []},
        ],
    })
    object_scope = (
        "Document.ЗаказКлиента,Catalog.Номенклатура,"
        "AccumulationRegister.ОстаткиТоваров"
    )
    httpserver.expect_request(
        "/references",
        query_string={"level": "tables", "objects": object_scope},
    ).respond_with_json([
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
    ])
    httpserver.expect_request(
        "/lineage",
        query_string={
            "objects": object_scope,
            "kinds": "basis,register_movement,manual_dataset_flow",
        },
    ).respond_with_json([
        {
            "upstream_object_type": "Catalogs",
            "upstream_name": "Номенклатура",
            "downstream_object_type": "Documents",
            "downstream_name": "ЗаказКлиента",
            "kind": "basis",
        },
        {
            "upstream_object_type": "Catalogs",
            "upstream_name": "Номенклатура",
            "downstream_object_type": "Documents",
            "downstream_name": "ЗаказКлиента",
            "kind": "manual_dataset_flow",
            "source": "manual",
            "confidence": "high",
            "description": "Ручная связь из расширения.",
            "details": {"origin": "extension_registry"},
        },
        {
            "upstream_object_type": "Documents",
            "upstream_name": "ЗаказКлиента",
            "downstream_object_type": "AccumulationRegisters",
            "downstream_name": "ОстаткиТоваров",
            "kind": "register_movement",
        },
    ])


def _event_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(event.get("entityUrn") or ""),
        str(event.get("aspectName") or ""),
        str(event.get("id") or ""),
    )


def _serialize(wus: list[MetadataWorkUnit]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for wu in wus:
        mcp = wu.metadata
        obj = pre_json_transform(mcp.to_obj())
        aspect = obj["aspect"]
        aspect_json = aspect.get("json")
        if aspect_json is None:
            value = aspect["value"]
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            aspect_json = json.loads(value)
        events.append({
            "id": wu.id,
            "entityType": obj["entityType"],
            "entityUrn": obj.get("entityUrn"),
            "aspectName": obj["aspectName"],
            "aspect": pre_json_transform(aspect_json),
        })
    return sorted(events, key=_event_key)


def test_onec_source_mcp_golden(httpserver: HTTPServer, tmp_path: Path) -> None:
    _setup_api(httpserver)
    source = _build_source(httpserver, tmp_path)

    actual = _serialize(list(source.get_workunits_internal()))
    if os.environ.get("UPDATE_ONEC_SOURCE_GOLDEN") == "1":
        _GOLDEN_PATH.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    expected = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

    assert actual == expected
    assert len(actual) > 20
    assert _GOLDEN_PATH.stat().st_size > 5_000
