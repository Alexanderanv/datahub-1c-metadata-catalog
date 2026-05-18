from __future__ import annotations

import pytest
from datahub.metadata.schema_classes import (
    BooleanTypeClass,
    DateTypeClass,
    ForeignKeyConstraintClass,
    NumberTypeClass,
    RecordTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    UnionTypeClass,
)

from datahub_1c.api.models import Attribute, AttributeType
from datahub_1c.mapping.schema_fields import (
    build_schema_fields,
    build_schema_metadata_workunit,
)
from datahub_1c.mapping.urn import ObjectKind


def _attr(name: str, types: list[tuple[str, bool]], role: str = "attribute", synonym: str | None = None) -> Attribute:
    return Attribute(
        name=name,
        synonym=synonym,
        types=[AttributeType(name=n, is_reference=r) for n, r in types],
        role=role,
    )


class TestBuildSchemaFieldsCatalog:
    def test_standard_attributes_first_and_complete(self) -> None:
        fields = build_schema_fields(
            standard_attrs=__import__("datahub_1c.mapping.standard_attributes", fromlist=["attributes_for"]).attributes_for(ObjectKind.CATALOG),
            user_attrs=[],
            object_name="Номенклатура",
        )
        paths = [f.fieldPath for f in fields]
        assert paths[:3] == ["Ref", "Code", "Description"]

    def test_ref_is_part_of_key(self) -> None:
        fields = build_schema_fields(
            standard_attrs=__import__("datahub_1c.mapping.standard_attributes", fromlist=["attributes_for"]).attributes_for(ObjectKind.CATALOG),
            user_attrs=[],
            object_name="Номенклатура",
        )
        ref = next(f for f in fields if f.fieldPath == "Ref")
        assert ref.isPartOfKey is True
        assert ref.nullable is False

    def test_all_standard_attributes_are_not_nullable(self) -> None:
        fields = build_schema_fields(
            standard_attrs=__import__("datahub_1c.mapping.standard_attributes", fromlist=["attributes_for"]).attributes_for(ObjectKind.CATALOG),
            user_attrs=[],
            object_name="Номенклатура",
        )
        assert all(f.nullable is False for f in fields)

    def test_ru_label_for_russian_object(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[],
            object_name="Номенклатура",
        )
        ref = next(f for f in fields if f.fieldPath == "Ref")
        assert ref.label == "Ссылка"

    def test_en_label_for_english_object(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[],
            object_name="Nomenclature",
        )
        ref = next(f for f in fields if f.fieldPath == "Ref")
        assert ref.label == "Ref"


class TestBuildSchemaFieldsUserAttributes:
    def test_user_attribute_path_is_transliterated(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[_attr("Артикул", [("Строка", False)], synonym="Артикул")],
            object_name="Номенклатура",
        )
        assert any(f.fieldPath == "Artikul" for f in fields)

    def test_user_attribute_label_is_synonym(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[_attr("Артикул", [("Строка", False)], synonym="Артикул товара")],
            object_name="Номенклатура",
        )
        f = next(f for f in fields if f.fieldPath == "Artikul")
        assert f.label == "Артикул товара"
        assert f.description == "Артикул товара"

    def test_user_attribute_is_not_nullable(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[_attr("Артикул", [("Строка", False)])],
            object_name="Номенклатура",
        )
        f = next(f for f in fields if f.fieldPath == "Artikul")
        assert f.nullable is False

    def test_description_preserves_original_name_when_field_path_is_transliterated(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[_attr("Артикул", [("Строка", False)], synonym="Артикул")],
            object_name="Номенклатура",
        )
        f = next(f for f in fields if f.fieldPath == "Artikul")
        assert f.description == "Артикул"

    def test_description_empty_when_label_equals_field_path(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[_attr("Article", [("Строка", False)], synonym="Article")],
            object_name="Nomenclature",
        )
        f = next(f for f in fields if f.fieldPath == "Article")
        assert f.description is None

    @pytest.mark.parametrize(
        ("attribute_name", "field_path"),
        [
            ("Лид", "Lid"),
            ("НетСтрокВДокументе", "NetStrokVDokumente"),
        ],
    )
    def test_document_attribute_description_keeps_original_1c_name(
        self,
        attribute_name: str,
        field_path: str,
    ) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.DOCUMENT),
            user_attrs=[_attr(attribute_name, [("Строка", False)], synonym=attribute_name)],
            object_name="ЗаказПокупателя",
        )
        f = next(f for f in fields if f.fieldPath == field_path)
        assert f.description == attribute_name

    def test_standard_role_attributes_are_skipped(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[
                _attr("Код", [("Строка", False)], role="standard"),
                _attr("Наименование", [("Строка", False)], role="standard"),
            ],
            object_name="Номенклатура",
        )
        assert sum(1 for f in fields if f.fieldPath == "Code") == 1
        assert sum(1 for f in fields if f.fieldPath == "Description") == 1

    def test_user_with_same_path_as_standard_is_skipped(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[_attr("Код", [("Строка", False)], role="attribute")],
            object_name="Номенклатура",
        )
        assert sum(1 for f in fields if f.fieldPath == "Code") == 1


class TestTypeMapping:
    def test_primitive_types(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.CATALOG),
            user_attrs=[
                _attr("Сумма", [("Число", False)]),
                _attr("ДатаОперации", [("Дата", False)]),
                _attr("Активен", [("Булево", False)]),
                _attr("Название", [("Строка", False)]),
            ],
            object_name="Номенклатура",
        )
        by_path = {f.fieldPath: f for f in fields}
        assert isinstance(by_path["Summa"].type.type, NumberTypeClass)
        assert isinstance(by_path["DataOperaczii"].type.type, DateTypeClass)
        assert isinstance(by_path["Aktiven"].type.type, BooleanTypeClass)
        assert isinstance(by_path["Nazvanie"].type.type, StringTypeClass)

    def test_reference_type_is_record(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.DOCUMENT),
            user_attrs=[_attr("Контрагент", [("Catalog.Контрагенты", True)])],
            object_name="Платёж",
        )
        f = next(f for f in fields if f.fieldPath == "Kontragent")
        assert isinstance(f.type.type, RecordTypeClass)
        assert f.nativeDataType == "Catalog.Контрагенты"

    def test_composite_type_is_union(self) -> None:
        from datahub_1c.mapping.standard_attributes import attributes_for
        fields = build_schema_fields(
            standard_attrs=attributes_for(ObjectKind.DOCUMENT),
            user_attrs=[_attr("Объект", [
                ("Catalog.Контрагенты", True),
                ("Document.Платёж", True),
            ])],
            object_name="Платёж",
        )
        f = next(f for f in fields if f.fieldPath == "Obekt")
        assert isinstance(f.type.type, UnionTypeClass)
        assert " | " in f.nativeDataType


class TestBuildSchemaMetadataWorkunit:
    def test_emits_workunit_with_platform_urn(self) -> None:
        wu = build_schema_metadata_workunit(
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Catalog.Nomenklatura,PROD)",
            dataset_name="Catalog.Nomenklatura",
            kind=ObjectKind.CATALOG,
            object_name="Номенклатура",
            user_attributes=[_attr("Артикул", [("Строка", False)])],
        )
        aspect = wu.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        assert aspect.platform == "urn:li:dataPlatform:1c-enterprise"
        paths = [f.fieldPath for f in aspect.fields]
        assert "Ref" in paths
        assert "Artikul" in paths

    def test_primary_keys_populated(self) -> None:
        wu = build_schema_metadata_workunit(
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Catalog.Nomenklatura,PROD)",
            dataset_name="Catalog.Nomenklatura",
            kind=ObjectKind.CATALOG,
            object_name="Номенклатура",
            user_attributes=[],
        )
        aspect = wu.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        assert "Ref" in (aspect.primaryKeys or [])

    def test_tabular_section_uses_ts_standard_attrs(self) -> None:
        wu = build_schema_metadata_workunit(
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.X.TP,PROD)",
            dataset_name="Document.X.TP",
            kind=ObjectKind.DOCUMENT,
            object_name="X",
            user_attributes=[],
            is_tabular_section=True,
        )
        aspect = wu.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        paths = [f.fieldPath for f in aspect.fields]
        assert paths == ["Ref", "LineNumber"]

    def test_foreign_keys_attached(self) -> None:
        fk = ForeignKeyConstraintClass(
            name="FK_Ref_to_Parent",
            foreignFields=["urn:li:schemaField:(urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.X,PROD),Ref)"],
            sourceFields=["urn:li:schemaField:(urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.X.TP,PROD),Ref)"],
            foreignDataset="urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.X,PROD)",
        )
        wu = build_schema_metadata_workunit(
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.X.TP,PROD)",
            dataset_name="Document.X.TP",
            kind=ObjectKind.DOCUMENT,
            object_name="X",
            user_attributes=[],
            is_tabular_section=True,
            foreign_keys=[fk],
        )
        aspect = wu.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        assert aspect.foreignKeys is not None
        assert aspect.foreignKeys[0].name == "FK_Ref_to_Parent"
