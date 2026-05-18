from __future__ import annotations

import json

from datahub.metadata.schema_classes import (
    BrowsePathsV2Class,
    ContainerClass,
    ContainerPropertiesClass,
    SubTypesClass,
)

from datahub_1c.api.models import MetadataObjectSummary
from datahub_1c.mapping.containers import (
    build_container_urn,
    build_container_workunits,
    build_infobase_workunits,
    build_type_folder_workunits,
)
from datahub_1c.mapping.custom_aspects import ONE_C_OBJECT_PROPERTIES
from datahub_1c.mapping.urn import (
    INFOBASE_CONTAINER_SUB_TYPE,
    TYPE_FOLDER_SUB_TYPE,
    ObjectKind,
    infobase_container_urn_for,
    type_folder_container_urn_for,
)

DOC_UUID = "88825e44-0d57-41a5-abd8-7a1bdad96c0e"
CATALOG_UUID = "deadbeef-0000-0000-0000-000000000001"
INFOBASE = "1c-test"


def _summary() -> MetadataObjectSummary:
    return MetadataObjectSummary(
        object_type="Documents",
        name="ПоступлениеТоваров",
        full_name="Document.ПоступлениеТоваров",
        synonym="Поступление товаров",
    )


def _collect(gen):
    return list(gen)


class TestBuildContainerUrn:
    def test_env_in_urn(self) -> None:
        prod = build_container_urn(infobase_name=INFOBASE, object_uuid=DOC_UUID, env="PROD")
        dev = build_container_urn(infobase_name=INFOBASE, object_uuid=DOC_UUID, env="DEV")
        assert prod != dev

    def test_infobase_in_urn(self) -> None:
        a = build_container_urn(infobase_name="1c-test", object_uuid=DOC_UUID, env="PROD")
        b = build_container_urn(infobase_name="1c-prod", object_uuid=DOC_UUID, env="PROD")
        assert a != b

    def test_urn_is_ascii(self) -> None:
        urn = build_container_urn(infobase_name=INFOBASE, object_uuid=DOC_UUID, env="PROD")
        assert urn.startswith("urn:li:container:")
        assert urn.isascii()


class TestBuildContainerWorkunits:
    def test_emits_five_aspects(self) -> None:
        wus = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        assert len(wus) == 5
        aspect_types = {type(w.metadata.aspect).__name__ for w in wus}
        assert "DataPlatformInstanceClass" not in aspect_types

    def test_parent_container_points_to_type_folder(self) -> None:
        wus = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        cl = next(w for w in wus if isinstance(w.metadata.aspect, ContainerClass))
        assert cl.metadata.aspect.container == type_folder_container_urn_for(  # type: ignore[union-attr]
            ObjectKind.DOCUMENT, infobase_name=INFOBASE, env="PROD",
        )

    def test_browse_path_points_to_infobase_and_type_folder(self) -> None:
        wus = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        bp = next(w for w in wus if isinstance(w.metadata.aspect, BrowsePathsV2Class))
        path = bp.metadata.aspect.path  # type: ignore[union-attr]
        assert [entry.urn for entry in path] == [
            infobase_container_urn_for(infobase_name=INFOBASE, env="PROD"),
            type_folder_container_urn_for(
                ObjectKind.DOCUMENT,
                infobase_name=INFOBASE,
                env="PROD",
            ),
        ]

    def test_container_properties_fields(self) -> None:
        wus = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        cp = next(w for w in wus if isinstance(w.metadata.aspect, ContainerPropertiesClass))
        aspect = cp.metadata.aspect
        assert isinstance(aspect, ContainerPropertiesClass)
        assert aspect.name == "Документ.ПоступлениеТоваров"
        assert aspect.qualifiedName == "Документ.ПоступлениеТоваров"
        assert aspect.description == "Поступление товаров"
        # customProperties содержит metadataUuid + metadataKind + transliteratedName.
        assert dict(aspect.customProperties) == {
            "canonicalFullName": "Document.ПоступлениеТоваров",
            "metadataKind": "Document",
            "metadataKindLabel": "Документ",
            "metadataUuid": DOC_UUID,
            "infobaseName": INFOBASE,
            "transliteratedName": "Document.PostuplenieTovarov",
        }

    def test_urn_is_uuid_based(self) -> None:
        """URN контейнера = `<uuid>:<env>`, без ENG-префикса."""
        wus = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        urn = wus[0].metadata.entityUrn
        assert urn.startswith("urn:li:container:")
        # ENG-префикс в URN отсутствует.
        assert "Document." not in urn

    def test_sub_types_matches_kind_spec(self) -> None:
        wus = _collect(build_container_workunits(
            kind=ObjectKind.CATALOG,
            summary=MetadataObjectSummary(
                object_type="Catalogs",
                name="Номенклатура",
                full_name="Catalog.Номенклатура",
                synonym=None,
            ),
            object_uuid=CATALOG_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        st = next(w for w in wus if isinstance(w.metadata.aspect, SubTypesClass))
        assert st.metadata.aspect.typeNames == ["Catalog"]  # type: ignore[union-attr]

    def test_one_c_object_properties_payload(self) -> None:
        wus = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT,
            summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
            configuration_name="ERP_PROD",
        ))
        one_c = next(
            w for w in wus
            if w.metadata.aspectName == ONE_C_OBJECT_PROPERTIES
        )
        payload = json.loads(one_c.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload["objectKind"] == "Документ"
        assert payload["fullName"] == "Документ.ПоступлениеТоваров"
        assert payload["synonym"] == "Поступление товаров"
        assert payload["configurationName"] == "ERP_PROD"
        assert payload["metadataUuid"] == DOC_UUID

    def test_urn_stable_for_same_input(self) -> None:
        """Идемпотентность: перезапуск ingestion не создаёт новые контейнеры."""
        wus_1 = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        wus_2 = _collect(build_container_workunits(
            kind=ObjectKind.DOCUMENT, summary=_summary(),
            object_uuid=DOC_UUID, infobase_name=INFOBASE, env="PROD",
        ))
        assert wus_1[0].metadata.entityUrn == wus_2[0].metadata.entityUrn


class TestBuildInfobaseWorkunits:
    def test_emits_three_aspects(self) -> None:
        wus = _collect(build_infobase_workunits(
            infobase_name=INFOBASE,
            display_name="Тестовая ИБ",
            env="PROD",
        ))
        assert len(wus) == 3
        aspect_types = {type(w.metadata.aspect).__name__ for w in wus}
        assert "DataPlatformInstanceClass" not in aspect_types

    def test_display_and_subtype(self) -> None:
        wus = _collect(build_infobase_workunits(
            infobase_name=INFOBASE,
            display_name="Тестовая ИБ",
            env="PROD",
        ))
        cp = next(w for w in wus if isinstance(w.metadata.aspect, ContainerPropertiesClass))
        st = next(w for w in wus if isinstance(w.metadata.aspect, SubTypesClass))
        assert cp.metadata.aspect.name == "Тестовая ИБ"  # type: ignore[union-attr]
        assert cp.metadata.aspect.qualifiedName == INFOBASE  # type: ignore[union-attr]
        assert st.metadata.aspect.typeNames == [INFOBASE_CONTAINER_SUB_TYPE]  # type: ignore[union-attr]

    def test_browse_path_is_root(self) -> None:
        wus = _collect(build_infobase_workunits(
            infobase_name=INFOBASE,
            display_name=INFOBASE,
            env="PROD",
        ))
        bp = next(w for w in wus if isinstance(w.metadata.aspect, BrowsePathsV2Class))
        assert bp.metadata.aspect.path == []  # type: ignore[union-attr]


class TestBuildTypeFolderWorkunits:
    def test_emits_four_aspects(self) -> None:
        """containerProperties + subTypes + container(parent infobase) + browsePathsV2.
        dataPlatformInstance намеренно не эмитим — иначе Navigate создаёт
        виртуальный узел «Default» для контейнеров с instance=None.
        """
        wus = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT, infobase_name=INFOBASE, env="PROD",
        ))
        assert len(wus) == 4
        aspect_types = {type(w.metadata.aspect).__name__ for w in wus}
        assert "DataPlatformInstanceClass" not in aspect_types

    def test_parent_and_browse_path_point_to_infobase(self) -> None:
        wus = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT, infobase_name=INFOBASE, env="PROD",
        ))
        cl = next(w for w in wus if isinstance(w.metadata.aspect, ContainerClass))
        bp = next(w for w in wus if isinstance(w.metadata.aspect, BrowsePathsV2Class))
        infobase_urn = infobase_container_urn_for(infobase_name=INFOBASE, env="PROD")
        assert cl.metadata.aspect.container == infobase_urn  # type: ignore[union-attr]
        assert [entry.urn for entry in bp.metadata.aspect.path] == [infobase_urn]  # type: ignore[union-attr]

    def test_display_name_is_plural(self) -> None:
        wus = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT, infobase_name=INFOBASE, env="PROD",
        ))
        cp = next(w for w in wus if isinstance(w.metadata.aspect, ContainerPropertiesClass))
        assert cp.metadata.aspect.name == "Документы"  # type: ignore[union-attr]
        assert cp.metadata.aspect.qualifiedName == "Документы"  # type: ignore[union-attr]

    def test_sub_type_is_kind_folder(self) -> None:
        wus = _collect(build_type_folder_workunits(
            kind=ObjectKind.CATALOG, infobase_name=INFOBASE, env="PROD",
        ))
        st = next(w for w in wus if isinstance(w.metadata.aspect, SubTypesClass))
        assert st.metadata.aspect.typeNames == [TYPE_FOLDER_SUB_TYPE]  # type: ignore[union-attr]

    def test_urn_stable_for_same_input(self) -> None:
        wus_1 = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT,
            infobase_name=INFOBASE,
            env="PROD",
        ))
        wus_2 = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT,
            infobase_name=INFOBASE,
            env="PROD",
        ))
        assert wus_1[0].metadata.entityUrn == wus_2[0].metadata.entityUrn

    def test_env_in_urn(self) -> None:
        prod = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT,
            infobase_name=INFOBASE,
            env="PROD",
        ))[0].metadata.entityUrn
        dev = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT,
            infobase_name=INFOBASE,
            env="DEV",
        ))[0].metadata.entityUrn
        assert prod != dev

    def test_urn_is_ascii(self) -> None:
        wus = _collect(build_type_folder_workunits(
            kind=ObjectKind.DOCUMENT,
            infobase_name=INFOBASE,
            env="PROD",
        ))
        assert wus[0].metadata.entityUrn.isascii()
