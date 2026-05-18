"""Эмиссия датасетов табличных частей объектов 1С.

ТЧ получает собственный dataset URN вида
``<infobase>.<object_uuid>.<tabular_section_uuid>``. ``Ref`` связывается с
``Ref`` родителя через ``ForeignKeyConstraint``; доменные связи пишутся
через ``oneCDomainRelationships``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    ContainerClass,
    DatasetPropertiesClass,
    ForeignKeyConstraintClass,
    SubTypesClass,
)

from datahub_1c.api.models import MetadataObjectSummary, TabularPart
from datahub_1c.mapping.browse_paths import build_browse_paths_v2_workunit
from datahub_1c.mapping.custom_aspects import (
    ONE_C_OBJECT_PROPERTIES,
    build_custom_aspect_workunit,
)
from datahub_1c.mapping.relationships import (
    REL_IS_TABULAR_PART_OF,
    build_relationships_workunit,
)
from datahub_1c.mapping.schema_fields import build_schema_metadata_workunit
from datahub_1c.mapping.urn import (
    TABULAR_SECTION_SUB_TYPE,
    ObjectKind,
    _legacy_translit_dataset_name,
    dataset_urn,
    display_full_name,
    schema_field_urn_for,
)

# objectKind, который кладём в oneCObjectProperties ТЧ. Не ObjectKind enum
# (он описывает только «верхнеуровневые» виды 1С), а отдельная строка.
OBJECT_KIND_TABULAR_SECTION: str = "TabularSection"
OBJECT_KIND_TABULAR_SECTION_LABEL: str = "ТабличнаяЧасть"


@dataclass(frozen=True)
class TabularPartEmission:
    """Результат эмиссии одной ТЧ."""

    tabular_section_urn: str
    workunits: tuple[MetadataWorkUnit, ...]


def _fk_ref_to_parent_ref(
    *,
    tp_dataset_urn: str,
    parent_dataset_urn: str,
) -> ForeignKeyConstraintClass:
    """``ForeignKeyConstraint`` ``TP.Ref → Parent.Ref``."""
    return ForeignKeyConstraintClass(
        name="FK_Ref_to_Parent",
        sourceFields=[schema_field_urn_for(tp_dataset_urn, "Ref")],
        foreignFields=[schema_field_urn_for(parent_dataset_urn, "Ref")],
        foreignDataset=parent_dataset_urn,
    )


def build_tabular_part_emission(
    *,
    parent_kind: ObjectKind,
    parent_summary: MetadataObjectSummary,
    parent_object_uuid: str,
    infobase_name: str,
    tabular_part: TabularPart,
    tabular_section_uuid: str,
    parent_dataset_urn: str,
    parent_container_urns: Sequence[str],
    env: str,
    overrides: Mapping[str, str] | None = None,
    configuration_name: str | None = None,
    include_relationships: bool = True,
) -> TabularPartEmission:
    if not parent_container_urns:
        raise ValueError("parent_container_urns must be non-empty for a tabular part")
    parent_container_urn = parent_container_urns[-1]
    tp_urn = dataset_urn(
        infobase_name=infobase_name,
        object_uuid=parent_object_uuid,
        tabular_section_uuid=tabular_section_uuid,
        env=env,
    )
    tp_transliterated_name = _legacy_translit_dataset_name(
        parent_kind, parent_summary.name,
        tabular_section=tabular_part.name,
        overrides=overrides,
    )
    parent_display_full_name = display_full_name(parent_kind, parent_summary.name)
    tp_display_name = f"{parent_display_full_name}.{tabular_part.name}"
    qualified_name = tp_display_name

    workunits: list[MetadataWorkUnit] = []

    # datasetProperties — display name + UUID-метаданные в customProperties.
    workunits.append(
        MetadataChangeProposalWrapper(
            entityUrn=tp_urn,
            aspect=DatasetPropertiesClass(
                name=tp_display_name,
                qualifiedName=qualified_name,
                description=tabular_part.synonym,
                customProperties={
                    "metadataKind": OBJECT_KIND_TABULAR_SECTION,
                    "metadataKindLabel": OBJECT_KIND_TABULAR_SECTION_LABEL,
                    "metadataUuid": tabular_section_uuid,
                    "infobaseName": infobase_name,
                    "parentObjectUuid": parent_object_uuid,
                    "canonicalFullName": f"{parent_summary.full_name}.{tabular_part.name}",
                    "transliteratedName": tp_transliterated_name,
                },
            ),
        ).as_workunit()
    )
    # subTypes
    workunits.append(
        MetadataChangeProposalWrapper(
            entityUrn=tp_urn,
            aspect=SubTypesClass(typeNames=[TABULAR_SECTION_SUB_TYPE]),
        ).as_workunit()
    )
    # container
    workunits.append(
        MetadataChangeProposalWrapper(
            entityUrn=tp_urn,
            aspect=ContainerClass(container=parent_container_urn),
        ).as_workunit()
    )
    # browsePathsV2 — глушим дефолтный split-by-dot и рисуем иерархию
    # ``type-folder → object-container`` (см. mapping/browse_paths.py).
    workunits.append(
        build_browse_paths_v2_workunit(
            entity_urn=tp_urn, parent_urns=parent_container_urns,
        )
    )
    # schemaMetadata + FK Ref → Parent.Ref
    workunits.append(
        build_schema_metadata_workunit(
            dataset_urn=tp_urn,
            dataset_name=tp_display_name,
            kind=parent_kind,
            object_name=parent_summary.name,
            user_attributes=tabular_part.attributes,
            overrides=overrides,
            is_tabular_section=True,
            foreign_keys=[_fk_ref_to_parent_ref(
                tp_dataset_urn=tp_urn,
                parent_dataset_urn=parent_dataset_urn,
            )],
        )
    )
    # oneCObjectProperties для ТЧ — отдельная запись в custom aspect.
    payload: dict[str, object] = {
        "objectKind": OBJECT_KIND_TABULAR_SECTION_LABEL,
        "fullName": qualified_name,
        "metadataUuid": tabular_section_uuid,
        "parentObjectUuid": parent_object_uuid,
    }
    if tabular_part.synonym:
        payload["synonym"] = tabular_part.synonym
    if configuration_name:
        payload["configurationName"] = configuration_name
    workunits.append(
        build_custom_aspect_workunit(
            entity_urn=tp_urn,
            entity_type="dataset",
            aspect_name=ONE_C_OBJECT_PROPERTIES,
            payload=payload,
            workunit_id=f"{tp_urn}-{ONE_C_OBJECT_PROPERTIES}",
        )
    )
    if include_relationships:
        # Доменное отношение `isTabularPartOf` на ТЧ.
        workunits.append(
            build_relationships_workunit(
                entity_urn=tp_urn,
                entity_type="dataset",
                relationships={REL_IS_TABULAR_PART_OF: [parent_dataset_urn]},
            )
        )

    return TabularPartEmission(
        tabular_section_urn=tp_urn,
        workunits=tuple(workunits),
    )


def build_tabular_part_workunits(
    **kwargs: object,
) -> Iterable[MetadataWorkUnit]:
    """Удобная обёртка над :func:`build_tabular_part_emission`,
    если URN ТЧ вызывающему коду не нужен (например, в unit-тесте)."""
    return build_tabular_part_emission(**kwargs).workunits  # type: ignore[arg-type]
