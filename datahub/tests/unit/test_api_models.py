from __future__ import annotations

import pytest
from pydantic import ValidationError

from datahub_1c.api.models import (
    Attribute,
    AttributeType,
    CatalogProperties,
    DbMapping,
    DocumentProperties,
    HealthResponse,
    LineageEdge,
    MetadataObjectDetail,
    MetadataObjectSummary,
    Reference,
    RegisterProperties,
    TabularPart,
)


class TestHealthResponse:
    def test_minimal(self) -> None:
        h = HealthResponse.model_validate({"status": "ok"})
        assert h.status == "ok"
        assert h.version is None

    def test_with_version(self) -> None:
        h = HealthResponse.model_validate({"status": "ok", "version": "1.2.3"})
        assert h.version == "1.2.3"

    def test_ignores_unknown_fields(self) -> None:
        """Forward-compat: 1С может добавить новые поля, это не должно ломать ingestion."""
        h = HealthResponse.model_validate({"status": "ok", "uptime_seconds": 42})
        assert h.status == "ok"


class TestMetadataObjectSummary:
    def test_full(self) -> None:
        s = MetadataObjectSummary.model_validate({
            "object_type": "Catalogs",
            "name": "Номенклатура",
            "full_name": "Catalog.Номенклатура",
            "synonym": "Номенклатура",
        })
        assert s.name == "Номенклатура"
        assert s.full_name == "Catalog.Номенклатура"

    def test_synonym_optional(self) -> None:
        s = MetadataObjectSummary.model_validate({
            "object_type": "Documents",
            "name": "Платёж",
            "full_name": "Document.Платёж",
        })
        assert s.synonym is None


class TestMetadataObjectDetail:
    def test_empty_attributes_list(self) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": "Catalogs",
            "name": "Пустой",
            "full_name": "Catalog.Пустой",
        })
        assert d.attributes == []

    def test_with_attributes(self) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": "Documents",
            "name": "Поступление",
            "full_name": "Document.Поступление",
            "attributes": [
                {"name": "Номер", "types": [{"name": "Строка", "is_reference": False}], "role": "standard"},
                {"name": "Контрагент", "types": [{"name": "Catalog.Контрагенты", "is_reference": True}]},
            ],
        })
        assert len(d.attributes) == 2
        assert d.attributes[0].role == "standard"
        assert d.attributes[1].role == "attribute"
        assert d.attributes[1].types[0].is_reference is True


class TestAttribute:
    def test_default_role_is_attribute(self) -> None:
        a = Attribute.model_validate({"name": "X", "types": []})
        assert a.role == "attribute"

    def test_max_length(self) -> None:
        a = Attribute.model_validate({
            "name": "Наименование",
            "types": [{"name": "Строка", "is_reference": False}],
            "max_length": 150,
        })
        assert a.max_length == 150

    def test_composite_type(self) -> None:
        a = Attribute.model_validate({
            "name": "Объект",
            "types": [
                {"name": "Catalog.Контрагенты", "is_reference": True},
                {"name": "Document.Платёж", "is_reference": True},
            ],
        })
        assert len(a.types) == 2
        assert all(t.is_reference for t in a.types)


class TestTabularPart:
    def test_tabular_part(self) -> None:
        tp = TabularPart.model_validate({
            "name": "Состав",
            "attributes": [{"name": "Номенклатура", "types": []}],
        })
        assert tp.name == "Состав"
        assert tp.attributes[0].name == "Номенклатура"


class TestReference:
    def test_tables_level(self) -> None:
        r = Reference.model_validate({
            "source_object_type": "Documents",
            "source_name": "Платёж",
            "target_object_type": "Catalogs",
            "target_name": "Контрагенты",
        })
        assert r.source_tabular_part is None
        assert r.source_attribute is None
        assert r.target_attribute is None

    def test_columns_level(self) -> None:
        r = Reference.model_validate({
            "source_object_type": "Documents",
            "source_name": "Платёж",
            "target_object_type": "Catalogs",
            "target_name": "Контрагенты",
            "source_tabular_part": "Товары",
            "source_attribute": "Контрагент",
            "target_attribute": "Ссылка",
        })
        assert r.source_tabular_part == "Товары"
        assert r.source_attribute == "Контрагент"
        assert r.target_attribute == "Ссылка"


class TestLineageEdge:
    def test_minimal(self) -> None:
        edge = LineageEdge.model_validate({
            "upstream_object_type": "Documents",
            "upstream_name": "ЗаказКлиента",
            "downstream_object_type": "AccumulationRegisters",
            "downstream_name": "Продажи",
            "kind": "register_movement",
        })
        assert edge.source == "metadata"
        assert edge.confidence == "medium"
        assert edge.details is None

    def test_full(self) -> None:
        edge = LineageEdge.model_validate({
            "upstream_object_type": "Documents",
            "upstream_name": "ЗаказКлиента",
            "downstream_object_type": "AccumulationRegisters",
            "downstream_name": "Продажи",
            "kind": "register_movement",
            "source": "metadata",
            "confidence": "high",
            "description": "Документ делает движения по регистру.",
            "details": {"register_full_name": "AccumulationRegister.Продажи"},
        })
        assert edge.confidence == "high"
        assert edge.details == {"register_full_name": "AccumulationRegister.Продажи"}

    def test_manual_dataset_flow(self) -> None:
        edge = LineageEdge.model_validate({
            "upstream_object_type": "Catalogs",
            "upstream_name": "Номенклатура",
            "downstream_object_type": "Documents",
            "downstream_name": "ЗаказКлиента",
            "kind": "manual_dataset_flow",
            "source": "manual",
            "confidence": "high",
            "details": {"origin": "extension_registry"},
        })
        assert edge.kind == "manual_dataset_flow"
        assert edge.source == "manual"
        assert edge.details == {"origin": "extension_registry"}


class TestDbMapping:
    def test_composite_type_mapping(self) -> None:
        """Составной тип → несколько колонок с разными purpose."""
        m = DbMapping.model_validate({
            "object_type": "Documents",
            "name": "Платёж",
            "tables": [
                {
                    "db_table_name": "_Document123",
                    "purpose": "Main",
                    "columns": [
                        {
                            "attribute_name": "Объект",
                            "db_columns": [
                                {"column_name": "_Fld_TYPE", "purpose": "type_discriminator"},
                                {"column_name": "_Fld_RTRef", "purpose": "reference_discriminator"},
                                {"column_name": "_FldRRef", "purpose": "reference"},
                                {"column_name": "_Fld_Val", "purpose": "value"},
                            ],
                        },
                    ],
                },
            ],
        })
        purposes = [c.purpose for c in m.tables[0].columns[0].db_columns]
        assert purposes == [
            "type_discriminator",
            "reference_discriminator",
            "reference",
            "value",
        ]

    def test_purpose_required_for_table(self) -> None:
        """`purpose` теперь required (без него нельзя различить
        Main/TabularSection/Totals — а значит и нельзя выбрать,
        строить ли Sibling-обвязку)."""
        with pytest.raises(ValidationError):
            DbMapping.model_validate({
                "object_type": "Catalogs", "name": "X",
                "tables": [{"db_table_name": "_Ref1", "columns": []}],
            })

    def test_db_table_name_required(self) -> None:
        with pytest.raises(ValidationError):
            DbMapping.model_validate({
                "object_type": "Catalogs", "name": "X",
                "tables": [{"purpose": "Main", "columns": []}],
            })

    def test_column_purpose_optional(self) -> None:
        """Для простых типов BSL не выставляет purpose — это OK."""
        m = DbMapping.model_validate({
            "object_type": "Catalogs", "name": "X",
            "tables": [
                {
                    "db_table_name": "_Ref1",
                    "purpose": "Main",
                    "columns": [
                        {
                            "attribute_name": "Имя",
                            "db_columns": [{"column_name": "_Description"}],
                        },
                    ],
                },
            ],
        })
        assert m.tables[0].columns[0].db_columns[0].purpose is None

    def test_aux_table_purposes_accepted(self) -> None:
        """Все «вспомогательные» назначения таблиц должны
        парситься без ошибок (Sibling под них не строим — это
        ответственность mapping/db_mapping.py, тут только DTO)."""
        for purpose in ("TabularSection", "Totals", "TotalsSliceFirst", "TotalsSliceLast"):
            m = DbMapping.model_validate({
                "object_type": "AccumulationRegisters", "name": "X",
                "tables": [{"db_table_name": "_T", "purpose": purpose, "columns": []}],
            })
            assert m.tables[0].purpose == purpose


class TestAttributeType:
    def test_primitive(self) -> None:
        t = AttributeType.model_validate({"name": "Строка", "is_reference": False})
        assert t.is_reference is False

    def test_reference(self) -> None:
        t = AttributeType.model_validate({"name": "Catalog.X", "is_reference": True})
        assert t.is_reference is True


class TestKindSpecificProperties:
    def test_catalog_properties_full(self) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": "Catalogs", "name": "Контрагенты",
            "full_name": "Catalog.Контрагенты",
            "attributes": [],
            "catalog_properties": {
                "is_hierarchical": True,
                "hierarchy_kind": "HierarchyFoldersAndItems",
                "has_owner": True,
                "owner_names": ["Catalog.Контрагенты", "Catalog.ФизическиеЛица"],
                "code_length": 11,
                "description_length": 150,
            },
        })
        assert isinstance(d.catalog_properties, CatalogProperties)
        assert d.catalog_properties.is_hierarchical is True
        assert d.catalog_properties.hierarchy_kind == "HierarchyFoldersAndItems"
        assert d.catalog_properties.owner_names == [
            "Catalog.Контрагенты",
            "Catalog.ФизическиеЛица",
        ]
        assert d.document_properties is None
        assert d.register_properties is None

    def test_document_properties(self) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": "Documents", "name": "Платёж",
            "full_name": "Document.Платёж",
            "attributes": [],
            "document_properties": {
                "is_postable": True,
                "numbering_periodicity": "Year",
                "number_length": 9,
            },
        })
        assert isinstance(d.document_properties, DocumentProperties)
        assert d.document_properties.is_postable is True
        assert d.document_properties.numbering_periodicity == "Year"

    def test_register_properties(self) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": "InformationRegisters", "name": "Курсы",
            "full_name": "InformationRegister.Курсы",
            "attributes": [],
            "register_properties": {
                "register_kind": "Information",
                "periodicity": "Day",
                "write_mode": "Independent",
            },
        })
        assert isinstance(d.register_properties, RegisterProperties)
        assert d.register_properties.register_kind == "Information"

    def test_register_properties_require_register_kind(self) -> None:
        with pytest.raises(ValidationError):
            MetadataObjectDetail.model_validate({
                "object_type": "InformationRegisters",
                "name": "Курсы",
                "full_name": "InformationRegister.Курсы",
                "attributes": [],
                "register_properties": {"periodicity": "Day"},
            })

    @pytest.mark.parametrize(
        "object_type,full_name,register_kind",
        [
            ("AccountingRegisters", "AccountingRegister.Управленческий", "Accounting"),
            ("CalculationRegisters", "CalculationRegister.Начисления", "Calculation"),
        ],
    )
    def test_extended_register_properties(
        self,
        object_type: str,
        full_name: str,
        register_kind: str,
    ) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": object_type,
            "name": "X",
            "full_name": full_name,
            "attributes": [],
            "register_properties": {"register_kind": register_kind},
        })
        assert isinstance(d.register_properties, RegisterProperties)
        assert d.register_properties.register_kind == register_kind

    def test_all_kind_props_absent_by_default(self) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": "Catalogs", "name": "X",
            "full_name": "Catalog.X", "attributes": [],
        })
        assert d.catalog_properties is None
        assert d.document_properties is None
        assert d.register_properties is None
        assert d.comment is None

    def test_comment_field(self) -> None:
        d = MetadataObjectDetail.model_validate({
            "object_type": "Catalogs", "name": "X",
            "full_name": "Catalog.X", "attributes": [],
            "comment": "Справочник контрагентов (клиентов и поставщиков).",
        })
        assert d.comment is not None
        assert "контрагентов" in d.comment
