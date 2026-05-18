from __future__ import annotations

import json

from datahub.metadata.schema_classes import (
    BrowsePathsV2Class,
    ContainerClass,
    DatasetPropertiesClass,
    GenericAspectClass,
    SubTypesClass,
)

from datahub_1c.api.models import MetadataObjectSummary
from datahub_1c.mapping.custom_aspects import ONE_C_OBJECT_PROPERTIES
from datahub_1c.mapping.datasets import build_dataset_workunits
from datahub_1c.mapping.urn import ObjectKind

DOC_UUID = "88825e44-0d57-41a5-abd8-7a1bdad96c0e"
INFOBASE = "1c-test"


def _summary(name: str = "ПоступлениеТоваров", synonym: str | None = "Поступление товаров") -> MetadataObjectSummary:
    return MetadataObjectSummary(
        object_type="Documents",
        name=name,
        full_name=f"Document.{name}",
        synonym=synonym,
    )


def _collect(gen):
    return list(gen)


def _aspect_label(wu) -> str:
    aspect = wu.metadata.aspect
    if isinstance(aspect, GenericAspectClass):
        return wu.metadata.aspectName
    return type(aspect).__name__


class TestBuildDatasetWorkunits:
    def test_emits_expected_aspects_without_container(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        labels = {_aspect_label(wu) for wu in wus}
        assert "DatasetPropertiesClass" in labels
        assert "SubTypesClass" in labels
        assert "BrowsePathsV2Class" in labels
        assert ONE_C_OBJECT_PROPERTIES in labels
        assert "ContainerClass" not in labels
        assert len(wus) == 4

    def test_emits_expected_aspects_with_container(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            parent_container_urns=("urn:li:container:xyz",),
        ))
        labels = [_aspect_label(wu) for wu in wus]
        assert labels.count("ContainerClass") == 1
        assert labels.count("BrowsePathsV2Class") == 1
        assert len(wus) == 5

    def test_browse_path_is_empty_without_container(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        bp = next(w for w in wus if isinstance(w.metadata.aspect, BrowsePathsV2Class))
        assert bp.metadata.aspect.path == []  # type: ignore[union-attr]

    def test_browse_path_points_to_single_container(self) -> None:
        container_urn = "urn:li:container:abc"
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            parent_container_urns=(container_urn,),
        ))
        bp = next(w for w in wus if isinstance(w.metadata.aspect, BrowsePathsV2Class))
        path = bp.metadata.aspect.path  # type: ignore[union-attr]
        assert len(path) == 1
        assert path[0].id == container_urn
        assert path[0].urn == container_urn

    def test_browse_path_preserves_order_of_parents(self) -> None:
        type_folder = "urn:li:container:type_folder"
        object_container = "urn:li:container:obj"
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            parent_container_urns=(type_folder, object_container),
        ))
        bp = next(w for w in wus if isinstance(w.metadata.aspect, BrowsePathsV2Class))
        path = bp.metadata.aspect.path  # type: ignore[union-attr]
        assert [e.urn for e in path] == [type_folder, object_container]
        # `container`-аспект указывает на ближайшего родителя.
        cl = next(w for w in wus if isinstance(w.metadata.aspect, ContainerClass))
        assert cl.metadata.aspect.container == object_container  # type: ignore[union-attr]

    def test_urn_is_uuid_based(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        urn = wus[0].metadata.entityUrn
        assert urn.isascii()
        assert DOC_UUID in urn
        assert "Document." not in urn
        assert urn.endswith(",PROD)")

    def test_dataset_properties_fields(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT,
            summary=_summary(synonym="Поступление товаров"),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            comment="Документ регистрирует поступление ТМЦ на склад",
        ))
        dp = next(w for w in wus if isinstance(w.metadata.aspect, DatasetPropertiesClass))
        aspect = dp.metadata.aspect
        assert isinstance(aspect, DatasetPropertiesClass)
        assert aspect.name == "Документ.ПоступлениеТоваров"
        assert aspect.qualifiedName == "Документ.ПоступлениеТоваров"
        assert "Поступление товаров" in (aspect.description or "")
        assert "регистрирует поступление" in (aspect.description or "")
        assert dict(aspect.customProperties) == {
            "canonicalFullName": "Document.ПоступлениеТоваров",
            "infobaseName": INFOBASE,
            "metadataKind": "Document",
            "metadataKindLabel": "Документ",
            "metadataUuid": DOC_UUID,
            "transliteratedName": "Document.PostuplenieTovarov",
        }

    def test_sub_types_contains_document(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        st = next(w for w in wus if isinstance(w.metadata.aspect, SubTypesClass))
        assert st.metadata.aspect.typeNames == ["Document"]  # type: ignore[union-attr]

    def test_container_link_target_matches(self) -> None:
        container_urn = "urn:li:container:abc"
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            parent_container_urns=(container_urn,),
        ))
        cl = next(w for w in wus if isinstance(w.metadata.aspect, ContainerClass))
        assert cl.metadata.aspect.container == container_urn  # type: ignore[union-attr]

    def test_one_c_object_properties_payload(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.CATALOG,
            summary=_summary(name="Номенклатура", synonym="Товары"),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            configuration_name="ERP_PROD",
        ))
        one_c = next(
            w for w in wus
            if w.metadata.aspectName == ONE_C_OBJECT_PROPERTIES
        )
        payload = json.loads(one_c.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload["objectKind"] == "Справочник"
        assert payload["fullName"] == "Справочник.Номенклатура"
        assert payload["synonym"] == "Товары"
        assert payload["configurationName"] == "ERP_PROD"
        assert payload["metadataUuid"] == DOC_UUID
        assert "attributesUuidMap" not in payload

    def test_attributes_uuid_map_in_payload(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            attributes_uuid_map={
                "Nomenklatura": "11111111-1111-1111-1111-111111111111",
                "Kontragent": "22222222-2222-2222-2222-222222222222",
            },
        ))
        one_c = next(
            w for w in wus if w.metadata.aspectName == ONE_C_OBJECT_PROPERTIES
        )
        payload = json.loads(one_c.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload["attributesUuidMap"] == {
            "Kontragent": "22222222-2222-2222-2222-222222222222",
            "Nomenklatura": "11111111-1111-1111-1111-111111111111",
        }

    def test_en_config_passes_through(self) -> None:
        summary = MetadataObjectSummary(
            object_type="Catalogs", name="Nomenklatura",
            full_name="Catalog.Nomenklatura", synonym=None,
        )
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.CATALOG, summary=summary,
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        dp = next(w for w in wus if isinstance(w.metadata.aspect, DatasetPropertiesClass))
        assert dp.metadata.aspect.name == "Справочник.Nomenklatura"  # type: ignore[union-attr]

    def test_overrides_applied_to_display_name(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            overrides={"ПоступлениеТоваров": "GoodsReceipt"},
        ))
        dp = next(w for w in wus if isinstance(w.metadata.aspect, DatasetPropertiesClass))
        assert dp.metadata.aspect.name == "Документ.ПоступлениеТоваров"  # type: ignore[union-attr]
        assert dp.metadata.aspect.customProperties["transliteratedName"] == "Document.GoodsReceipt"  # type: ignore[union-attr]
        assert "GoodsReceipt" not in wus[0].metadata.entityUrn

    def test_no_description_when_empty(self) -> None:
        wus = _collect(build_dataset_workunits(
            kind=ObjectKind.DOCUMENT,
            summary=_summary(synonym=None),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        dp = next(w for w in wus if isinstance(w.metadata.aspect, DatasetPropertiesClass))
        assert dp.metadata.aspect.description is None  # type: ignore[union-attr]
