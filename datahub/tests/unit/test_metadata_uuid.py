from __future__ import annotations

import io
from pathlib import Path

import pytest

from datahub_1c.mapping.metadata_uuid import (
    MetadataUuidIndex,
    parse_config_dump_info,
    supported_eng_prefixes,
)
from datahub_1c.mapping.urn import ObjectKind

# Каноничные UUID — взяты из фикстуры ниже, удобно сослаться по имени.
DOC_UUID = "88825e44-0d57-41a5-abd8-7a1bdad96c0e"
DOC_ATTR_UUID = "11111111-2222-3333-4444-555555555555"
DOC_TS_UUID = "7660073c-26c1-458d-ba3b-7974acb8dceb"
DOC_TS_ATTR_UUID = "aaaa1111-bbbb-2222-cccc-3333dddd4444"
CATALOG_UUID = "deadbeef-0000-0000-0000-000000000001"
CATALOG_ATTR_UUID = "deadbeef-0000-0000-0000-000000000002"
INFO_REG_UUID = "f1f1f1f1-2222-3333-4444-555555555555"
INFO_REG_DIM_UUID = "f1f1f1f1-2222-3333-4444-666666666666"
INFO_REG_RES_UUID = "f1f1f1f1-2222-3333-4444-777777777777"
ACC_REG_UUID = "abc12345-6789-abcd-ef01-23456789abcd"
ACC_REG_ATTR_UUID = "abc12345-6789-abcd-ef01-23456789abce"
CHAR_PLAN_UUID = "12340000-0000-0000-0000-000000000001"
CHART_OF_ACCOUNTS_UUID = "12340000-0000-0000-0000-000000000002"
CHART_OF_CALCULATION_TYPES_UUID = "12340000-0000-0000-0000-000000000003"
ENUM_UUID = "ffff0000-0000-0000-0000-000000000001"
CONSTANT_UUID = "00000000-0000-0000-0000-000000000099"
ACCOUNTING_REG_UUID = "00000000-0000-0000-0000-0000000000aa"
ACCOUNTING_REG_RES_UUID = "00000000-0000-0000-0000-0000000000ab"
CALCULATION_REG_UUID = "00000000-0000-0000-0000-0000000000ac"
CALCULATION_REG_DIM_UUID = "00000000-0000-0000-0000-0000000000ad"
HTTP_SERVICE_UUID = "00000000-0000-0000-0000-0000000000ae"
HTTP_METHOD_UUID = "00000000-0000-0000-0000-0000000000af"
WEB_SERVICE_UUID = "00000000-0000-0000-0000-0000000000b0"
WEB_OPERATION_UUID = "00000000-0000-0000-0000-0000000000b1"


XML_FIXTURE = f"""<?xml version="1.0" encoding="UTF-8"?>
<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo" format="Hierarchical" version="2.20">
  <ConfigVersions>
    <Metadata name="Document.ЗаказПокупателя" id="{DOC_UUID}" configVersion="d017">
      <Metadata name="Document.ЗаказПокупателя.Attribute.Контрагент" id="{DOC_ATTR_UUID}"/>
      <Metadata name="Document.ЗаказПокупателя.TabularSection.Товары" id="{DOC_TS_UUID}">
        <Metadata name="Document.ЗаказПокупателя.TabularSection.Товары.Attribute.Номенклатура" id="{DOC_TS_ATTR_UUID}"/>
        <Metadata name="Document.ЗаказПокупателя.TabularSection.Товары.Attribute.Количество" id="{DOC_TS_ATTR_UUID[:-1]}5"/>
      </Metadata>
      <Metadata name="Document.ЗаказПокупателя.Form.Основная" id="{DOC_UUID[:-1]}1"/>
      <Metadata name="Document.ЗаказПокупателя.StandardAttribute.Ref" id="{DOC_UUID[:-1]}2"/>
    </Metadata>
    <Metadata name="Document.ЗаказПокупателя.ManagerModule" id="{DOC_UUID}.7" configVersion="eacc"/>
    <Metadata name="Document.ЗаказПокупателя.Help" id="{DOC_UUID}.5"/>
    <Metadata name="Catalog.Номенклатура" id="{CATALOG_UUID}">
      <Metadata name="Catalog.Номенклатура.Attribute.Артикул" id="{CATALOG_ATTR_UUID}"/>
    </Metadata>
    <Metadata name="InformationRegister.ЦеныНоменклатуры" id="{INFO_REG_UUID}">
      <Metadata name="InformationRegister.ЦеныНоменклатуры.Dimension.Номенклатура" id="{INFO_REG_DIM_UUID}"/>
      <Metadata name="InformationRegister.ЦеныНоменклатуры.Resource.Цена" id="{INFO_REG_RES_UUID}"/>
    </Metadata>
    <Metadata name="AccumulationRegister.ОстаткиТоваров" id="{ACC_REG_UUID}">
      <Metadata name="AccumulationRegister.ОстаткиТоваров.Attribute.Активность" id="{ACC_REG_ATTR_UUID}"/>
    </Metadata>
    <Metadata name="ChartOfCharacteristicTypes.ВидыЗначений" id="{CHAR_PLAN_UUID}"/>
    <Metadata name="ChartOfAccounts.Управленческий" id="{CHART_OF_ACCOUNTS_UUID}"/>
    <Metadata name="ChartOfCalculationTypes.Начисления" id="{CHART_OF_CALCULATION_TYPES_UUID}"/>
    <Metadata name="Enum.СтавкиНДС" id="{ENUM_UUID}"/>
    <Metadata name="Constant.ВалютаУчёта" id="{CONSTANT_UUID}"/>
    <Metadata name="Constant.ВалютаУчёта.ValueManagerModule" id="{CONSTANT_UUID}.0"/>
    <Metadata name="AccountingRegister.Управленческий" id="{ACCOUNTING_REG_UUID}">
      <Metadata name="AccountingRegister.Управленческий.Resource.Сумма" id="{ACCOUNTING_REG_RES_UUID}"/>
    </Metadata>
    <Metadata name="CalculationRegister.Начисления" id="{CALCULATION_REG_UUID}">
      <Metadata name="CalculationRegister.Начисления.Dimension.Сотрудник" id="{CALCULATION_REG_DIM_UUID}"/>
    </Metadata>
    <Metadata name="HTTPService.OrdersApi" id="{HTTP_SERVICE_UUID}">
      <Metadata name="HTTPService.OrdersApi.URLTemplate.Orders" id="{HTTP_SERVICE_UUID}.1">
        <Metadata name="HTTPService.OrdersApi.URLTemplate.Orders.Method.Post" id="{HTTP_METHOD_UUID}"/>
      </Metadata>
    </Metadata>
    <Metadata name="WebService.Exchange" id="{WEB_SERVICE_UUID}">
      <Metadata name="WebService.Exchange.Operation.Send" id="{WEB_OPERATION_UUID}"/>
      <Metadata name="WebService.Exchange.Operation.Send.Parameter.Payload" id="{WEB_OPERATION_UUID}.1"/>
    </Metadata>
  </ConfigVersions>
</ConfigDumpInfo>
"""


@pytest.fixture()
def index() -> MetadataUuidIndex:
    """Распарсить фикстуру и вернуть индекс — общий для большинства тестов."""
    return parse_config_dump_info(io.BytesIO(XML_FIXTURE.encode("utf-8")))


class TestObjects:
    def test_document_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(ObjectKind.DOCUMENT, "ЗаказПокупателя") == DOC_UUID

    def test_catalog_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(ObjectKind.CATALOG, "Номенклатура") == CATALOG_UUID

    def test_information_register_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(ObjectKind.INFORMATION_REGISTER, "ЦеныНоменклатуры") == INFO_REG_UUID

    def test_accumulation_register_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(ObjectKind.ACCUMULATION_REGISTER, "ОстаткиТоваров") == ACC_REG_UUID

    def test_chart_of_characteristic_types_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(
            ObjectKind.CHART_OF_CHARACTERISTIC_TYPES, "ВидыЗначений",
        ) == CHAR_PLAN_UUID

    def test_chart_of_accounts_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(
            ObjectKind.CHART_OF_ACCOUNTS, "Управленческий",
        ) == CHART_OF_ACCOUNTS_UUID

    def test_chart_of_calculation_types_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(
            ObjectKind.CHART_OF_CALCULATION_TYPES, "Начисления",
        ) == CHART_OF_CALCULATION_TYPES_UUID

    def test_constant_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(ObjectKind.CONSTANT, "ВалютаУчёта") == CONSTANT_UUID

    def test_accounting_register_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(
            ObjectKind.ACCOUNTING_REGISTER, "Управленческий",
        ) == ACCOUNTING_REG_UUID

    def test_calculation_register_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(
            ObjectKind.CALCULATION_REGISTER, "Начисления",
        ) == CALCULATION_REG_UUID

    def test_enumeration_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(ObjectKind.ENUMERATION, "СтавкиНДС") == ENUM_UUID

    def test_unknown_object_returns_none(self, index: MetadataUuidIndex) -> None:
        assert index.object_uuid(ObjectKind.DOCUMENT, "НетТакого") is None


class TestIntegrationServices:
    def test_http_service_uuid(self, index: MetadataUuidIndex) -> None:
        assert (
            index.integration_service_uuid("HTTPServices", "OrdersApi")
            == HTTP_SERVICE_UUID
        )

    def test_http_method_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.integration_endpoint_uuid(
            "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
        ) == HTTP_METHOD_UUID

    def test_web_service_uuid(self, index: MetadataUuidIndex) -> None:
        assert (
            index.integration_service_uuid("WebServices", "Exchange")
            == WEB_SERVICE_UUID
        )

    def test_web_operation_uuid(self, index: MetadataUuidIndex) -> None:
        assert index.integration_endpoint_uuid(
            "WebService.Exchange.Operation.Send",
        ) == WEB_OPERATION_UUID

    def test_web_operation_parameter_not_indexed_as_endpoint(
        self, index: MetadataUuidIndex,
    ) -> None:
        assert index.integration_endpoint_uuid(
            "WebService.Exchange.Operation.Send.Parameter.Payload",
        ) is None


class TestTabularSections:
    def test_known_ts(self, index: MetadataUuidIndex) -> None:
        assert index.tabular_section_uuid(
            ObjectKind.DOCUMENT, "ЗаказПокупателя", "Товары",
        ) == DOC_TS_UUID

    def test_unknown_ts_returns_none(self, index: MetadataUuidIndex) -> None:
        assert index.tabular_section_uuid(
            ObjectKind.DOCUMENT, "ЗаказПокупателя", "Услуги",
        ) is None


class TestAttributes:
    def test_user_attribute_of_document(self, index: MetadataUuidIndex) -> None:
        assert index.attribute_uuid(
            ObjectKind.DOCUMENT, "ЗаказПокупателя", None, "Контрагент",
        ) == DOC_ATTR_UUID

    def test_user_attribute_of_catalog(self, index: MetadataUuidIndex) -> None:
        assert index.attribute_uuid(
            ObjectKind.CATALOG, "Номенклатура", None, "Артикул",
        ) == CATALOG_ATTR_UUID

    def test_dimension_of_information_register(self, index: MetadataUuidIndex) -> None:
        # Resource/Dimension трактуются индексом наравне с Attribute.
        assert index.attribute_uuid(
            ObjectKind.INFORMATION_REGISTER, "ЦеныНоменклатуры", None, "Номенклатура",
        ) == INFO_REG_DIM_UUID

    def test_resource_of_information_register(self, index: MetadataUuidIndex) -> None:
        assert index.attribute_uuid(
            ObjectKind.INFORMATION_REGISTER, "ЦеныНоменклатуры", None, "Цена",
        ) == INFO_REG_RES_UUID

    def test_attribute_of_tabular_section(self, index: MetadataUuidIndex) -> None:
        assert index.attribute_uuid(
            ObjectKind.DOCUMENT, "ЗаказПокупателя", "Товары", "Номенклатура",
        ) == DOC_TS_ATTR_UUID

    def test_resource_of_accounting_register(self, index: MetadataUuidIndex) -> None:
        assert index.attribute_uuid(
            ObjectKind.ACCOUNTING_REGISTER, "Управленческий", None, "Сумма",
        ) == ACCOUNTING_REG_RES_UUID

    def test_dimension_of_calculation_register(self, index: MetadataUuidIndex) -> None:
        assert index.attribute_uuid(
            ObjectKind.CALCULATION_REGISTER, "Начисления", None, "Сотрудник",
        ) == CALCULATION_REG_DIM_UUID

    def test_unknown_attribute_returns_none(self, index: MetadataUuidIndex) -> None:
        assert index.attribute_uuid(
            ObjectKind.DOCUMENT, "ЗаказПокупателя", None, "НетТакого",
        ) is None


class TestServiceNodesAreIgnored:
    def test_manager_module_not_in_index(self, index: MetadataUuidIndex) -> None:
        """``<Metadata id="<uuid>.7" name="...ManagerModule">`` не индексируется."""
        # ManagerModule имеет name `Document.ЗаказПокупателя.ManagerModule` —
        # это 3 сегмента, не вписывается в нашу схему. Главное — не ронять.
        # Тест проверяет, что объект остался валидным (UUID без суффикса).
        assert index.object_uuid(ObjectKind.DOCUMENT, "ЗаказПокупателя") == DOC_UUID

    def test_form_node_ignored(self, index: MetadataUuidIndex) -> None:
        """Form-узлы 4-сегментные с id-суффиксом — не попадают в attributes."""
        assert index.attribute_uuid(
            ObjectKind.DOCUMENT, "ЗаказПокупателя", None, "Основная",
        ) is None

    def test_standard_attribute_role_not_indexed(self, index: MetadataUuidIndex) -> None:
        """Реквизиты роли StandardAttribute мы не индексируем — стандартные
        реквизиты в коннекторе определены статически (standard_attributes.py)."""
        assert index.attribute_uuid(
            ObjectKind.DOCUMENT, "ЗаказПокупателя", None, "Ref",
        ) is None


class TestUnsupportedKindsIgnored:
    """Неизвестные префиксы вне ObjectKind пропускаются без ошибок."""

    def test_unknown_prefix_not_indexed(self) -> None:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
            '<ConfigVersions>'
            '<Metadata name="BusinessProcess.Согласование" '
            'id="abcdef12-3456-7890-abcd-ef1234567890"/>'
            '</ConfigVersions>'
            '</ConfigDumpInfo>'
        )
        idx = parse_config_dump_info(io.BytesIO(xml.encode("utf-8")))
        assert idx.objects == {}


class TestUuidNormalization:
    def test_uuid_is_lowercased(self) -> None:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
            '<ConfigVersions>'
            '<Metadata name="Catalog.Тест" id="ABCDEF12-3456-7890-ABCD-EF1234567890"/>'
            '</ConfigVersions>'
            '</ConfigDumpInfo>'
        )
        idx = parse_config_dump_info(io.BytesIO(xml.encode("utf-8")))
        uuid = idx.object_uuid(ObjectKind.CATALOG, "Тест")
        assert uuid == "abcdef12-3456-7890-abcd-ef1234567890"

    def test_hyphens_preserved(self) -> None:
        """Дефисы в UUID сохраняются (читаемый формат, как в XML)."""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
            '<ConfigVersions>'
            '<Metadata name="Catalog.Тест" id="abcdef12-3456-7890-abcd-ef1234567890"/>'
            '</ConfigVersions>'
            '</ConfigDumpInfo>'
        )
        idx = parse_config_dump_info(io.BytesIO(xml.encode("utf-8")))
        uuid = idx.object_uuid(ObjectKind.CATALOG, "Тест")
        assert uuid is not None
        assert uuid.count("-") == 4

    def test_invalid_id_skipped(self) -> None:
        """Не-UUID id (например, пустой или мусор) — без падения, без записи."""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
            '<ConfigVersions>'
            '<Metadata name="Catalog.A" id=""/>'
            '<Metadata name="Catalog.B" id="not-a-uuid"/>'
            '<Metadata name="Catalog.C" id="abcdef12-3456-7890-abcd-ef1234567890"/>'
            '</ConfigVersions>'
            '</ConfigDumpInfo>'
        )
        idx = parse_config_dump_info(io.BytesIO(xml.encode("utf-8")))
        assert idx.object_uuid(ObjectKind.CATALOG, "A") is None
        assert idx.object_uuid(ObjectKind.CATALOG, "B") is None
        assert idx.object_uuid(ObjectKind.CATALOG, "C") is not None


class TestReadFromFile:
    def test_parse_from_path(self, tmp_path: Path) -> None:
        """Можно передать путь как ``str``, не только file-like."""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
            '<ConfigVersions>'
            f'<Metadata name="Catalog.Тест" id="{CATALOG_UUID}"/>'
            '</ConfigVersions>'
            '</ConfigDumpInfo>'
        )
        path = tmp_path / "ConfigDumpInfo.xml"
        path.write_text(xml, encoding="utf-8")
        idx = parse_config_dump_info(str(path))
        assert idx.object_uuid(ObjectKind.CATALOG, "Тест") == CATALOG_UUID

    def test_parse_from_pathlib_path(self, tmp_path: Path) -> None:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">'
            '<ConfigVersions>'
            f'<Metadata name="Catalog.Тест" id="{CATALOG_UUID}"/>'
            '</ConfigVersions>'
            '</ConfigDumpInfo>'
        )
        path = tmp_path / "ConfigDumpInfo.xml"
        path.write_text(xml, encoding="utf-8")
        idx = parse_config_dump_info(path)
        assert idx.object_uuid(ObjectKind.CATALOG, "Тест") == CATALOG_UUID


class TestSupportedPrefixes:
    def test_returns_current_supported_kinds(self) -> None:
        prefixes = set(supported_eng_prefixes())
        assert prefixes == {
            "Constant", "Catalog", "Document", "ChartOfCharacteristicTypes",
            "ChartOfAccounts", "ChartOfCalculationTypes",
            "InformationRegister", "AccumulationRegister",
            "AccountingRegister", "CalculationRegister", "Enum",
            "HTTPService", "WebService",
        }
