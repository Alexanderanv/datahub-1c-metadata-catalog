from __future__ import annotations

import pytest

from datahub_1c.mapping.standard_attributes import (
    StandardAttribute,
    attributes_for,
    attributes_for_tabular_section,
    pick_label,
    supported_kinds,
)
from datahub_1c.mapping.urn import ObjectKind


def _paths(attrs: tuple[StandardAttribute, ...]) -> list[str]:
    return [a.field_path for a in attrs]


class TestCatalog:
    def test_catalog_attributes(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.CATALOG))) == [
            "Ref", "Code", "Description", "DeletionMark", "Predefined",
            "Parent", "Owner", "IsFolder",
        ]

    def test_ref_is_part_of_key(self) -> None:
        ref = next(a for a in attributes_for(ObjectKind.CATALOG) if a.field_path == "Ref")
        assert ref.is_part_of_key is True


class TestConstant:
    def test_constant_has_no_static_standard_attributes(self) -> None:
        assert list(attributes_for(ObjectKind.CONSTANT)) == []


class TestDocument:
    def test_document_attributes(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.DOCUMENT))) == [
            "Ref", "Number", "Date", "Posted", "DeletionMark",
        ]


class TestChartOfCharacteristicTypes:
    def test_includes_type_attribute(self) -> None:
        assert "Type" in _paths(tuple(attributes_for(ObjectKind.CHART_OF_CHARACTERISTIC_TYPES)))

    def test_inherits_catalog_like_structure(self) -> None:
        paths = _paths(tuple(attributes_for(ObjectKind.CHART_OF_CHARACTERISTIC_TYPES)))
        for expected in ("Ref", "Code", "Description", "DeletionMark"):
            assert expected in paths


class TestChartOfAccounts:
    def test_catalog_like_structure(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.CHART_OF_ACCOUNTS))) == [
            "Ref", "Code", "Description", "DeletionMark", "Predefined",
            "Parent", "IsFolder",
        ]


class TestChartOfCalculationTypes:
    def test_catalog_like_structure(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.CHART_OF_CALCULATION_TYPES))) == [
            "Ref", "Code", "Description", "DeletionMark", "Predefined",
            "Parent", "IsFolder",
        ]


class TestInformationRegister:
    def test_information_register_attributes(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.INFORMATION_REGISTER))) == [
            "Period", "Recorder", "LineNumber", "Active",
        ]


class TestAccumulationRegister:
    def test_accumulation_register_attributes(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.ACCUMULATION_REGISTER))) == [
            "Period", "Recorder", "LineNumber", "Active", "RecordType",
        ]


class TestAccountingRegister:
    def test_accounting_register_attributes(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.ACCOUNTING_REGISTER))) == [
            "Period", "Recorder", "LineNumber", "Active", "RecordType",
            "AccountDr", "AccountCr",
        ]


class TestCalculationRegister:
    def test_calculation_register_attributes(self) -> None:
        assert _paths(tuple(attributes_for(ObjectKind.CALCULATION_REGISTER))) == [
            "Recorder", "LineNumber", "Active", "RegistrationPeriod",
            "CalculationType", "BegOfActionPeriod", "EndOfActionPeriod",
        ]


class TestTabularSection:
    def test_tabular_section_attributes(self) -> None:
        assert _paths(tuple(attributes_for_tabular_section())) == ["Ref", "LineNumber"]


class TestPickLabel:
    def test_ru_config_uses_label_ru(self) -> None:
        attrs = attributes_for(ObjectKind.DOCUMENT)
        date = next(a for a in attrs if a.field_path == "Date")
        assert pick_label(date, object_name="ПоступлениеТоваров") == "Дата"

    def test_en_config_uses_label_en(self) -> None:
        attrs = attributes_for(ObjectKind.DOCUMENT)
        date = next(a for a in attrs if a.field_path == "Date")
        assert pick_label(date, object_name="IncomingGoods") == "Date"


class TestCoverage:
    def test_all_supported_kinds_covered(self) -> None:
        """Изменение состава видов требует синхронизации справочника реквизитов."""
        assert set(supported_kinds()) == {
            ObjectKind.CONSTANT,
            ObjectKind.CATALOG,
            ObjectKind.DOCUMENT,
            ObjectKind.CHART_OF_CHARACTERISTIC_TYPES,
            ObjectKind.CHART_OF_ACCOUNTS,
            ObjectKind.CHART_OF_CALCULATION_TYPES,
            ObjectKind.INFORMATION_REGISTER,
            ObjectKind.ACCUMULATION_REGISTER,
            ObjectKind.ACCOUNTING_REGISTER,
            ObjectKind.CALCULATION_REGISTER,
            ObjectKind.ENUMERATION,
        }

    @pytest.mark.parametrize("kind", list(ObjectKind))
    def test_each_kind_has_declared_attrs(self, kind: ObjectKind) -> None:
        attrs = attributes_for(kind)
        if kind is ObjectKind.CONSTANT:
            assert list(attrs) == []
        else:
            assert len(attrs) > 0

    def test_all_standard_attributes_are_not_nullable(self) -> None:
        """В 1С отсутствующие значения представлены значениями по умолчанию /
        пустыми ссылками, а не SQL NULL. В UI DataHub не должен быть бейдж
        Nullable для стандартных 1С-реквизитов."""
        for kind in supported_kinds():
            assert all(attr.nullable is False for attr in attributes_for(kind))
        assert all(attr.nullable is False for attr in attributes_for_tabular_section())


class TestAttributeImmutability:
    def test_attributes_are_frozen_dataclasses(self) -> None:
        """Любая попытка мутации справочника снаружи — FrozenInstanceError."""
        import dataclasses

        attrs = attributes_for(ObjectKind.CATALOG)
        ref = attrs[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.field_path = "Mutated"  # type: ignore[misc]
