from __future__ import annotations

import base64

import pytest
from pytest_httpserver import HTTPServer

from datahub_1c.api.client import OneCApiClient


@pytest.fixture
def client(httpserver: HTTPServer) -> OneCApiClient:
    return OneCApiClient(
        base_url=httpserver.url_for(""),
        username="Администратор",
        password="secret",
    )


def _expect_basic_auth(user: str, pwd: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class TestHealth:
    def test_health_ok(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        httpserver.expect_request(
            "/health",
            headers=_expect_basic_auth("Администратор", "secret"),
        ).respond_with_json({"status": "ok", "version": "1.0.0"})

        h = client.health()
        assert h.status == "ok"
        assert h.version == "1.0.0"


class TestListObjects:
    def test_without_filter(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        httpserver.expect_request("/objects").respond_with_json([
            {"object_type": "Catalogs", "name": "Номенклатура",
             "full_name": "Catalog.Номенклатура"},
        ])
        items = client.list_objects()
        assert [i.name for i in items] == ["Номенклатура"]

    def test_with_types_filter(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        httpserver.expect_request(
            "/objects",
            query_string={"types": "Catalogs,Documents"},
        ).respond_with_json([])
        assert client.list_objects(types=["Catalogs", "Documents"]) == []


class TestGetObjectDetail:
    def test_detail(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        httpserver.expect_request("/objects/Documents/Поступление").respond_with_json({
            "object_type": "Documents",
            "name": "Поступление",
            "full_name": "Document.Поступление",
            "synonym": "Поступление товаров",
            "attributes": [
                {"name": "Контрагент",
                 "types": [{"name": "Catalog.Контрагенты", "is_reference": True}]},
            ],
        })
        d = client.get_object_detail("Documents", "Поступление")
        assert d.synonym == "Поступление товаров"
        assert d.attributes[0].types[0].is_reference is True


class TestGetTabularParts:
    def test_with_parts(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        httpserver.expect_request(
            "/objects/Documents/Поступление/tabular-parts",
        ).respond_with_json([
            {"name": "Состав", "attributes": []},
            {"name": "ДополнительныеРеквизиты", "attributes": []},
        ])
        parts = client.get_tabular_parts("Documents", "Поступление")
        assert [p.name for p in parts] == ["Состав", "ДополнительныеРеквизиты"]

    def test_404_returns_empty(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        httpserver.expect_request(
            "/objects/Catalogs/ПростойСправочник/tabular-parts",
        ).respond_with_data("", status=404)
        assert client.get_tabular_parts("Catalogs", "ПростойСправочник") == []


class TestGetReferences:
    def test_default_level_tables(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        httpserver.expect_request(
            "/references",
            query_string={"level": "tables"},
        ).respond_with_json([
            {"source_object_type": "Documents", "source_name": "Платёж",
             "target_object_type": "Catalogs", "target_name": "Контрагенты"},
        ])
        refs = client.get_references()
        assert refs[0].source_attribute is None

    def test_columns_level_with_types(
        self, httpserver: HTTPServer, client: OneCApiClient,
    ) -> None:
        httpserver.expect_request(
            "/references",
            query_string={"level": "columns", "types": "Documents"},
        ).respond_with_json([
            {"source_object_type": "Documents", "source_name": "Платёж",
             "target_object_type": "Catalogs", "target_name": "Контрагенты",
             "source_tabular_part": "Товары",
             "source_attribute": "Контрагент", "target_attribute": "Ссылка"},
        ])
        refs = client.get_references(types=["Documents"], level="columns")
        assert refs[0].source_tabular_part == "Товары"
        assert refs[0].source_attribute == "Контрагент"
        assert refs[0].target_attribute == "Ссылка"

    def test_with_objects_filter(
        self, httpserver: HTTPServer, client: OneCApiClient,
    ) -> None:
        httpserver.expect_request(
            "/references",
            query_string={
                "level": "tables",
                "objects": "Document.Платёж,Catalog.Контрагенты",
            },
        ).respond_with_json([
            {"source_object_type": "Documents", "source_name": "Платёж",
             "target_object_type": "Catalogs", "target_name": "Контрагенты"},
        ])
        refs = client.get_references(
            objects=["Document.Платёж", "Catalog.Контрагенты"],
        )
        assert refs[0].target_name == "Контрагенты"


class TestGetLineage:
    def test_with_objects_and_kinds_filter(
        self, httpserver: HTTPServer, client: OneCApiClient,
    ) -> None:
        httpserver.expect_request(
            "/lineage",
            query_string={
                "objects": "Document.ЗаказКлиента,AccumulationRegister.Продажи",
                "kinds": "basis,register_movement,manual_dataset_flow",
            },
        ).respond_with_json([
            {
                "upstream_object_type": "Documents",
                "upstream_name": "ЗаказКлиента",
                "downstream_object_type": "AccumulationRegisters",
                "downstream_name": "Продажи",
                "kind": "register_movement",
                "source": "metadata",
                "confidence": "medium",
            },
        ])

        edges = client.get_lineage(
            objects=["Document.ЗаказКлиента", "AccumulationRegister.Продажи"],
            kinds=["basis", "register_movement", "manual_dataset_flow"],
        )

        assert edges[0].kind == "register_movement"
        assert edges[0].downstream_name == "Продажи"


class TestGetIntegrationServices:
    def test_with_scope_filters(
        self, httpserver: HTTPServer, client: OneCApiClient,
    ) -> None:
        httpserver.expect_request(
            "/integration-services",
            query_string={
                "types": "HTTPServices",
                "services": "HTTPService.OrdersApi",
                "endpoints": "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
            },
        ).respond_with_json([
            {
                "service_type": "HTTPServices",
                "name": "OrdersApi",
                "full_name": "HTTPService.OrdersApi",
                "root_url": "orders",
                "endpoints": [
                    {
                        "endpoint_type": "http_method",
                        "name": "Post",
                        "full_name": (
                            "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post"
                        ),
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
        ])

        services = client.get_integration_services(
            types=["HTTPServices"],
            services=["HTTPService.OrdersApi"],
            endpoints=["HTTPService.OrdersApi.URLTemplate.Orders.Method.Post"],
        )

        assert len(services) == 1
        assert services[0].service_type == "HTTPServices"
        assert services[0].endpoints[0].http_method == "POST"
        assert services[0].endpoints[0].input_objects[0].full_name == (
            "Document.ЗаказКлиента"
        )


class TestGetDbMapping:
    def test_mapping(self, httpserver: HTTPServer, client: OneCApiClient) -> None:
        # Формат ответа /db-mapping (с 2026-04):
        # * `db_table_name` (раньше pg_table_name) — нейтральный к СУБД префикс,
        # * `purpose` (Main / TabularSection / Totals / TotalsSliceFirst /
        #   TotalsSliceLast) — заменил `is_tabular_part` + `tabular_part_name`,
        # * `db_columns` без `pg_type` (1С API не отдаёт SQL-тип).
        httpserver.expect_request("/db-mapping/Catalogs/Номенклатура").respond_with_json({
            "object_type": "Catalogs",
            "name": "Номенклатура",
            "tables": [
                {
                    "db_table_name": "_Reference42",
                    "purpose": "Main",
                    "columns": [
                        {
                            "attribute_name": "Ссылка",
                            "db_columns": [
                                {"column_name": "_IDRRef", "purpose": "reference"},
                            ],
                        },
                    ],
                },
            ],
        })
        m = client.get_db_mapping("Catalogs", "Номенклатура")
        assert m.tables[0].db_table_name == "_Reference42"
        assert m.tables[0].purpose == "Main"
        assert m.tables[0].columns[0].db_columns[0].purpose == "reference"


class TestContextManager:
    def test_used_as_context_manager(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/health").respond_with_json({"status": "ok"})
        with OneCApiClient(httpserver.url_for(""), "u", "p") as c:
            assert c.health().status == "ok"
