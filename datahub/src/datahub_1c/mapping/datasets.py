"""Эмиссия базовых аспектов Dataset для объектов 1С.

Dataset URN строится на UUID объекта метаданных. Русские имена и legacy
транслит сохраняются в свойствах датасета, а не участвуют в URN.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    ContainerClass,
    DatasetPropertiesClass,
    SubTypesClass,
)

from datahub_1c.api.models import MetadataObjectSummary
from datahub_1c.mapping.browse_paths import build_browse_paths_v2_workunit
from datahub_1c.mapping.custom_aspects import (
    ONE_C_OBJECT_PROPERTIES,
    build_custom_aspect_workunit,
)
from datahub_1c.mapping.urn import (
    ObjectKind,
    _legacy_translit_dataset_name,
    dataset_urn,
    display_full_name,
    russian_singular_label,
    spec_for,
)


def _dataset_properties_wu(
    *,
    urn: str,
    display_name: str,
    full_name: str,
    synonym: str | None,
    comment: str | None,
    custom_properties: Mapping[str, str],
) -> MetadataWorkUnit:
    description_parts = [p for p in (synonym, comment) if p]
    description = "\n\n".join(description_parts) if description_parts else None
    aspect = DatasetPropertiesClass(
        name=display_name,
        qualifiedName=full_name,
        description=description,
        customProperties=dict(custom_properties),
    )
    return MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect).as_workunit()


def _subtypes_wu(*, urn: str, sub_type: str) -> MetadataWorkUnit:
    return MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=SubTypesClass(typeNames=[sub_type]),
    ).as_workunit()


def _container_link_wu(*, urn: str, container_urn: str) -> MetadataWorkUnit:
    return MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=ContainerClass(container=container_urn),
    ).as_workunit()


def _object_properties_payload(
    *,
    kind: ObjectKind,
    summary: MetadataObjectSummary,
    object_uuid: str,
    configuration_name: str | None,
    attributes_uuid_map: Mapping[str, str] | None,
) -> Mapping[str, object]:
    """Поля должны совпадать с ``OneCObjectProperties.pdl``."""
    payload: dict[str, object] = {
        "objectKind": russian_singular_label(kind),
        "fullName": display_full_name(kind, summary.name),
        "metadataUuid": object_uuid,
    }
    if summary.synonym:
        payload["synonym"] = summary.synonym
    if configuration_name:
        payload["configurationName"] = configuration_name
    if attributes_uuid_map:
        # Сортировка ключей — для детерминированности JSON-сериализации
        # (упрощает сравнение payload в тестах и diff между прогонами).
        payload["attributesUuidMap"] = dict(sorted(attributes_uuid_map.items()))
    return payload


def build_dataset_workunits(
    *,
    kind: ObjectKind,
    summary: MetadataObjectSummary,
    object_uuid: str,
    infobase_name: str,
    env: str,
    overrides: Mapping[str, str] | None = None,
    parent_container_urns: Sequence[str] = (),
    configuration_name: str | None = None,
    comment: str | None = None,
    attributes_uuid_map: Mapping[str, str] | None = None,
) -> Iterable[MetadataWorkUnit]:
    urn = dataset_urn(infobase_name=infobase_name, object_uuid=object_uuid, env=env)
    transliterated_name = _legacy_translit_dataset_name(
        kind, summary.name, overrides=overrides,
    )
    display_name = display_full_name(kind, summary.name)
    custom_properties = {
        "metadataKind": spec_for(kind).english_term,
        "metadataKindLabel": str(kind),
        "metadataUuid": object_uuid,
        "infobaseName": infobase_name,
        "canonicalFullName": summary.full_name,
        "transliteratedName": transliterated_name,
    }

    yield _dataset_properties_wu(
        urn=urn,
        display_name=display_name,
        full_name=display_name,
        synonym=summary.synonym,
        comment=comment,
        custom_properties=custom_properties,
    )
    yield _subtypes_wu(urn=urn, sub_type=spec_for(kind).sub_type)

    if parent_container_urns:
        yield _container_link_wu(urn=urn, container_urn=parent_container_urns[-1])

    # browsePathsV2 эмитим всегда — чтобы дефолтный pipeline-трансформер
    # не сгенерировал параллельный путь split-by-dot из URN-имени
    # датасета, и чтобы Navigate UI правильно построил иерархию
    # ``type-folder → object-container → dataset`` (см. mapping/browse_paths.py).
    yield build_browse_paths_v2_workunit(
        entity_urn=urn, parent_urns=parent_container_urns,
    )

    yield build_custom_aspect_workunit(
        entity_urn=urn,
        entity_type="dataset",
        aspect_name=ONE_C_OBJECT_PROPERTIES,
        payload=_object_properties_payload(
            kind=kind, summary=summary,
            object_uuid=object_uuid,
            configuration_name=configuration_name,
            attributes_uuid_map=attributes_uuid_map,
        ),
        workunit_id=f"{urn}-{ONE_C_OBJECT_PROPERTIES}",
    )
