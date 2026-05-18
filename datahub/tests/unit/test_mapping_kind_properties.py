from __future__ import annotations

import json

from datahub_1c.api.models import (
    CatalogProperties,
    DocumentProperties,
    RegisterProperties,
)
from datahub_1c.mapping.custom_aspects import (
    ONE_C_CATALOG_PROPERTIES,
    ONE_C_DOCUMENT_PROPERTIES,
    ONE_C_REGISTER_PROPERTIES,
)
from datahub_1c.mapping.kind_properties import (
    build_catalog_properties_workunit,
    build_document_properties_workunit,
    build_register_properties_workunit,
)

URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Catalog.X,PROD)"


def _payload(wu):
    return json.loads(wu.metadata.aspect.value.decode("ascii"))


class TestCatalog:
    def test_full(self) -> None:
        wu = build_catalog_properties_workunit(
            entity_urn=URN,
            properties=CatalogProperties(
                is_hierarchical=True,
                hierarchy_kind="HierarchyFoldersAndItems",
                has_owner=True,
                owner_names=["Catalog.Контрагенты", "Catalog.ФизическиеЛица"],
                code_length=11,
                description_length=150,
            ),
        )
        assert wu is not None
        assert wu.metadata.aspectName == ONE_C_CATALOG_PROPERTIES
        payload = _payload(wu)
        assert payload == {
            "isHierarchical": True,
            "hierarchyKind": "HierarchyFoldersAndItems",
            "hasOwner": True,
            "ownerNames": ["Catalog.Контрагенты", "Catalog.ФизическиеЛица"],
            "codeLength": 11,
            "descriptionLength": 150,
        }

    def test_none_returns_none(self) -> None:
        assert build_catalog_properties_workunit(entity_urn=URN, properties=None) is None

    def test_all_fields_empty_returns_none(self) -> None:
        """CatalogProperties создан, но все поля None → workunit не нужен."""
        assert build_catalog_properties_workunit(
            entity_urn=URN, properties=CatalogProperties(),
        ) is None

    def test_partial_payload(self) -> None:
        wu = build_catalog_properties_workunit(
            entity_urn=URN,
            properties=CatalogProperties(is_hierarchical=False),
        )
        assert wu is not None
        assert _payload(wu) == {"isHierarchical": False}


class TestDocument:
    def test_full(self) -> None:
        wu = build_document_properties_workunit(
            entity_urn=URN,
            properties=DocumentProperties(
                is_postable=True,
                numerator_name="",
                numbering_periodicity="Year",
                number_length=9,
            ),
        )
        assert wu is not None
        assert wu.metadata.aspectName == ONE_C_DOCUMENT_PROPERTIES
        payload = _payload(wu)
        assert payload["isPostable"] is True
        assert payload["numberingPeriodicity"] == "Year"
        # numerator_name="" — пустая строка не None, попадает в payload как есть
        assert payload["numeratorName"] == ""

    def test_none_returns_none(self) -> None:
        assert build_document_properties_workunit(entity_urn=URN, properties=None) is None


class TestRegister:
    def test_full(self) -> None:
        wu = build_register_properties_workunit(
            entity_urn=URN,
            properties=RegisterProperties(
                register_kind="Accumulation",
                totals_enabled=True,
            ),
        )
        assert wu is not None
        assert wu.metadata.aspectName == ONE_C_REGISTER_PROPERTIES
        payload = _payload(wu)
        assert payload["registerKind"] == "Accumulation"
        assert payload["totalsEnabled"] is True
        assert "periodicity" not in payload

    def test_none_returns_none(self) -> None:
        assert build_register_properties_workunit(entity_urn=URN, properties=None) is None

    def test_register_kind_fallback_is_serialized(self) -> None:
        wu = build_register_properties_workunit(
            entity_urn=URN,
            properties=RegisterProperties.model_construct(totals_enabled=True),
            register_kind="Accumulation",
        )

        assert wu is not None
        assert _payload(wu) == {
            "registerKind": "Accumulation",
            "totalsEnabled": True,
        }

    def test_partial_register_without_kind_is_skipped(self) -> None:
        assert (
            build_register_properties_workunit(
                entity_urn=URN,
                properties=RegisterProperties.model_construct(totals_enabled=True),
            )
            is None
        )

    def test_accounting_and_calculation_kinds_are_serialized(self) -> None:
        accounting = build_register_properties_workunit(
            entity_urn=URN,
            properties=RegisterProperties(register_kind="Accounting"),
        )
        calculation = build_register_properties_workunit(
            entity_urn=URN,
            properties=RegisterProperties(register_kind="Calculation"),
        )

        assert accounting is not None
        assert calculation is not None
        assert _payload(accounting)["registerKind"] == "Accounting"
        assert _payload(calculation)["registerKind"] == "Calculation"
