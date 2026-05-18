from __future__ import annotations

import json

from datahub.metadata.schema_classes import (
    BrowsePathsV2Class,
    ContainerClass,
    DatasetPropertiesClass,
    SchemaMetadataClass,
    SubTypesClass,
)

from datahub_1c.api.models import Attribute, AttributeType, MetadataObjectSummary, TabularPart
from datahub_1c.mapping.custom_aspects import ONE_C_OBJECT_PROPERTIES
from datahub_1c.mapping.relationships import REL_IS_TABULAR_PART_OF
from datahub_1c.mapping.tabular_parts import (
    OBJECT_KIND_TABULAR_SECTION,
    OBJECT_KIND_TABULAR_SECTION_LABEL,
    build_tabular_part_emission,
)
from datahub_1c.mapping.urn import TABULAR_SECTION_SUB_TYPE, ObjectKind

PARENT_SUMMARY = MetadataObjectSummary(
    object_type="Documents",
    name="ПоступлениеТоваров",
    full_name="Document.ПоступлениеТоваров",
    synonym="Поступление товаров",
)
DOC_UUID = "88825e44-0d57-41a5-abd8-7a1bdad96c0e"
TS_UUID = "7660073c-26c1-458d-ba3b-7974acb8dceb"
INFOBASE = "1c-test"
PARENT_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,"
    f"{INFOBASE}.{DOC_UUID},PROD)"
)
INFOBASE_CONTAINER = "urn:li:container:infobase"
TYPE_FOLDER = "urn:li:container:typefolder"
PARENT_CONTAINER = "urn:li:container:deadbeef"


def _tp(name: str = "Состав", synonym: str | None = "Состав товаров",
        attrs: list[Attribute] | None = None) -> TabularPart:
    return TabularPart(name=name, synonym=synonym, attributes=attrs or [])


def _emit(**overrides):
    kwargs = dict(
        parent_kind=ObjectKind.DOCUMENT, parent_summary=PARENT_SUMMARY,
        parent_object_uuid=DOC_UUID,
        infobase_name=INFOBASE,
        tabular_part=_tp(), tabular_section_uuid=TS_UUID,
        parent_dataset_urn=PARENT_URN,
        parent_container_urns=(INFOBASE_CONTAINER, TYPE_FOLDER, PARENT_CONTAINER),
        env="PROD",
    )
    kwargs.update(overrides)
    return build_tabular_part_emission(**kwargs)


class TestBuildTabularPartEmission:
    def test_urn_is_uuid_based(self) -> None:
        em = _emit()
        # URN ТЧ = `<parent_uuid>.<ts_uuid>`, без транслит-имён.
        assert f"{INFOBASE}.{DOC_UUID}.{TS_UUID}" in em.tabular_section_urn
        assert em.tabular_section_urn.startswith("urn:li:dataset:")
        # Транслит имени родителя/ТЧ в URN отсутствует.
        assert "PostuplenieTovarov" not in em.tabular_section_urn
        assert "Sostav" not in em.tabular_section_urn

    def test_emits_seven_workunits(self) -> None:
        em = _emit()
        assert len(em.workunits) == 7

    def test_browse_path_contains_infobase_type_folder_and_object_container(self) -> None:
        em = _emit()
        bp = next(wu for wu in em.workunits if isinstance(wu.metadata.aspect, BrowsePathsV2Class))
        path = bp.metadata.aspect.path  # type: ignore[union-attr]
        assert [e.urn for e in path] == [
            INFOBASE_CONTAINER,
            TYPE_FOLDER,
            PARENT_CONTAINER,
        ]

    def test_empty_parent_containers_is_rejected(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="parent_container_urns"):
            _emit(parent_container_urns=())

    def test_subtype_is_tabular_section(self) -> None:
        em = _emit()
        st = next(wu for wu in em.workunits if isinstance(wu.metadata.aspect, SubTypesClass))
        assert st.metadata.aspect.typeNames == [TABULAR_SECTION_SUB_TYPE]  # type: ignore[union-attr]

    def test_container_points_to_parent(self) -> None:
        em = _emit()
        cl = next(wu for wu in em.workunits if isinstance(wu.metadata.aspect, ContainerClass))
        assert cl.metadata.aspect.container == PARENT_CONTAINER  # type: ignore[union-attr]

    def test_dataset_properties_qualified_name(self) -> None:
        em = _emit()
        dp = next(wu for wu in em.workunits if isinstance(wu.metadata.aspect, DatasetPropertiesClass))
        aspect = dp.metadata.aspect
        assert isinstance(aspect, DatasetPropertiesClass)
        assert aspect.qualifiedName == "Документ.ПоступлениеТоваров.Состав"
        assert aspect.name == "Документ.ПоступлениеТоваров.Состав"
        assert aspect.description == "Состав товаров"
        # customProperties: metadataKind/Uuid/parentObjectUuid/transliteratedName.
        assert dict(aspect.customProperties) == {
            "canonicalFullName": "Document.ПоступлениеТоваров.Состав",
            "infobaseName": INFOBASE,
            "metadataKind": OBJECT_KIND_TABULAR_SECTION,
            "metadataKindLabel": "ТабличнаяЧасть",
            "metadataUuid": TS_UUID,
            "parentObjectUuid": DOC_UUID,
            "transliteratedName": "Document.PostuplenieTovarov.Sostav",
        }

    def test_schema_has_ref_and_line_number(self) -> None:
        em = _emit()
        sm = next(wu for wu in em.workunits if isinstance(wu.metadata.aspect, SchemaMetadataClass))
        aspect = sm.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        paths = [f.fieldPath for f in aspect.fields]
        assert paths[:2] == ["Ref", "LineNumber"]

    def test_schema_has_user_attributes(self) -> None:
        em = _emit(tabular_part=_tp(attrs=[
            Attribute(name="Номенклатура",
                      types=[AttributeType(name="Catalog.Номенклатура", is_reference=True)]),
            Attribute(name="Количество", types=[AttributeType(name="Число", is_reference=False)]),
        ]))
        sm = next(wu for wu in em.workunits if isinstance(wu.metadata.aspect, SchemaMetadataClass))
        aspect = sm.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        paths = [f.fieldPath for f in aspect.fields]
        assert "Nomenklatura" in paths
        assert "Kolichestvo" in paths

    def test_foreign_key_ref_to_parent(self) -> None:
        em = _emit()
        sm = next(wu for wu in em.workunits if isinstance(wu.metadata.aspect, SchemaMetadataClass))
        aspect = sm.metadata.aspect
        assert isinstance(aspect, SchemaMetadataClass)
        assert aspect.foreignKeys is not None
        fk = aspect.foreignKeys[0]
        assert fk.foreignDataset == PARENT_URN
        assert any("Ref" in sf for sf in fk.sourceFields)
        assert any("Ref" in ff for ff in fk.foreignFields)

    def test_one_c_object_properties_payload(self) -> None:
        em = _emit(configuration_name="ERP_PROD")
        one_c = next(
            wu for wu in em.workunits
            if wu.metadata.aspectName == ONE_C_OBJECT_PROPERTIES
        )
        payload = json.loads(one_c.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload["objectKind"] == OBJECT_KIND_TABULAR_SECTION_LABEL
        assert payload["fullName"] == "Документ.ПоступлениеТоваров.Состав"
        assert payload["synonym"] == "Состав товаров"
        assert payload["configurationName"] == "ERP_PROD"
        assert payload["metadataUuid"] == TS_UUID
        assert payload["parentObjectUuid"] == DOC_UUID

    def test_is_tabular_part_of_relationship(self) -> None:
        em = _emit()
        from datahub_1c.mapping.custom_aspects import ONE_C_DOMAIN_RELATIONSHIPS
        rels = next(wu for wu in em.workunits if wu.metadata.aspectName == ONE_C_DOMAIN_RELATIONSHIPS)
        payload = json.loads(rels.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload == {REL_IS_TABULAR_PART_OF: [PARENT_URN]}
