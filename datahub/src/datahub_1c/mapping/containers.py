"""Эмиссия ``Container`` для объектов 1С с табличными частями.

Контейнер создаётся только для объекта, у которого реально есть ТЧ. В OSS
DataHub ``dataPlatformInstance`` для таких контейнеров не эмитится, иначе
Navigate добавляет лишний узел ``Default``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    ContainerClass,
    ContainerPropertiesClass,
    SubTypesClass,
)

from datahub_1c.api.models import MetadataObjectSummary
from datahub_1c.mapping.browse_paths import build_browse_paths_v2_workunit
from datahub_1c.mapping.custom_aspects import (
    ONE_C_OBJECT_PROPERTIES,
    build_custom_aspect_workunit,
)
from datahub_1c.mapping.urn import (
    INFOBASE_CONTAINER_SUB_TYPE,
    TYPE_FOLDER_SUB_TYPE,
    ObjectKind,
    _legacy_translit_dataset_name,
    container_urn_for,
    display_full_name,
    infobase_container_urn_for,
    russian_singular_label,
    spec_for,
    type_folder_container_urn_for,
    type_folder_display,
)


def _properties_wu(
    *,
    urn: str,
    name: str,
    qualified_name: str,
    description: str | None,
    custom_properties: Mapping[str, str] | None = None,
) -> MetadataWorkUnit:
    return MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=ContainerPropertiesClass(
            name=name,
            qualifiedName=qualified_name,
            description=description,
            customProperties=dict(custom_properties) if custom_properties else None,
        ),
    ).as_workunit()


def _subtypes_wu(*, urn: str, sub_type: str) -> MetadataWorkUnit:
    return MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=SubTypesClass(typeNames=[sub_type]),
    ).as_workunit()


def build_container_urn(*, infobase_name: str, object_uuid: str, env: str) -> str:
    return container_urn_for(
        infobase_name=infobase_name,
        object_uuid=object_uuid,
        env=env,
    )


def build_infobase_workunits(
    *,
    infobase_name: str,
    display_name: str,
    env: str,
) -> Iterable[MetadataWorkUnit]:
    urn = infobase_container_urn_for(infobase_name=infobase_name, env=env)
    yield _properties_wu(
        urn=urn,
        name=display_name,
        qualified_name=infobase_name,
        description=None,
        custom_properties={"infobaseName": infobase_name},
    )
    yield _subtypes_wu(urn=urn, sub_type=INFOBASE_CONTAINER_SUB_TYPE)
    yield build_browse_paths_v2_workunit(entity_urn=urn, parent_urns=())


def build_type_folder_workunits(
    *,
    kind: ObjectKind,
    infobase_name: str,
    env: str,
) -> Iterable[MetadataWorkUnit]:
    urn = type_folder_container_urn_for(kind, infobase_name=infobase_name, env=env)
    infobase_urn = infobase_container_urn_for(infobase_name=infobase_name, env=env)
    display = type_folder_display(kind)

    yield _properties_wu(
        urn=urn,
        name=display,
        qualified_name=display,
        description=None,
    )
    yield _subtypes_wu(urn=urn, sub_type=TYPE_FOLDER_SUB_TYPE)
    # dataPlatformInstance НЕ эмитим на type-folder намеренно:
    # контейнер с dataPlatformInstance(instance=None) создаёт в Navigate
    # виртуальный узел «Default», дублирующий иерархию. Платформа и так
    # ассоциируется через dataset URN'ы и browsePathsV2 датасетов внутри.
    yield MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=ContainerClass(container=infobase_urn),
    ).as_workunit()
    yield build_browse_paths_v2_workunit(entity_urn=urn, parent_urns=(infobase_urn,))


def build_container_workunits(
    *,
    kind: ObjectKind,
    summary: MetadataObjectSummary,
    object_uuid: str,
    infobase_name: str,
    env: str,
    overrides: Mapping[str, str] | None = None,
    configuration_name: str | None = None,
) -> Iterable[MetadataWorkUnit]:
    urn = build_container_urn(
        infobase_name=infobase_name,
        object_uuid=object_uuid,
        env=env,
    )
    transliterated_name = _legacy_translit_dataset_name(
        kind, summary.name, overrides=overrides,
    )
    display_name = display_full_name(kind, summary.name)
    infobase_urn = infobase_container_urn_for(infobase_name=infobase_name, env=env)
    type_folder_urn = type_folder_container_urn_for(
        kind,
        infobase_name=infobase_name,
        env=env,
    )

    container_custom_properties = {
        "metadataKind": spec_for(kind).english_term,
        "metadataKindLabel": str(kind),
        "metadataUuid": object_uuid,
        "infobaseName": infobase_name,
        "canonicalFullName": summary.full_name,
        "transliteratedName": transliterated_name,
    }

    yield _properties_wu(
        urn=urn,
        name=display_name,
        qualified_name=display_name,
        description=summary.synonym,
        custom_properties=container_custom_properties,
    )
    yield _subtypes_wu(urn=urn, sub_type=spec_for(kind).sub_type)
    # dataPlatformInstance НЕ эмитим — по той же причине, что и на type-folder:
    # instance=None → "Default" bucket в Navigate. Платформа ассоциируется
    # через URN датасетов и их browsePathsV2, контейнеры появляются как
    # folder-ноды из browse-дерева.

    # `container` нужен для Lineage/GraphQL, `browsePathsV2` — для Navigate.
    yield MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=ContainerClass(container=type_folder_urn),
    ).as_workunit()
    yield build_browse_paths_v2_workunit(
        entity_urn=urn, parent_urns=(infobase_urn, type_folder_urn),
    )

    payload: dict[str, object] = {
        "objectKind": russian_singular_label(kind),
        "fullName": display_full_name(kind, summary.name),
        "metadataUuid": object_uuid,
    }
    if summary.synonym:
        payload["synonym"] = summary.synonym
    if configuration_name:
        payload["configurationName"] = configuration_name

    yield build_custom_aspect_workunit(
        entity_urn=urn,
        entity_type="container",
        aspect_name=ONE_C_OBJECT_PROPERTIES,
        payload=payload,
        workunit_id=f"{urn}-{ONE_C_OBJECT_PROPERTIES}",
    )
