"""Эмиссия доменных отношений ``oneCDomainRelationships``.

Это не DataHub lineage: lineage строится отдельно через
``ForeignKeyConstraint`` и ``Upstream``. Пустые списки в payload не пишутся,
чтобы частичный ingestion не стирал уже записанные связи.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from datahub.ingestion.api.workunit import MetadataWorkUnit

from datahub_1c.mapping.custom_aspects import (
    ONE_C_DOMAIN_RELATIONSHIPS,
    build_custom_aspect_workunit,
)

# Имена полей PDL-аспекта (camelCase, 1:1 с `OneCDomainRelationships.pdl`).
REL_HAS_TABULAR_PART: str = "hasTabularPart"
REL_IS_TABULAR_PART_OF: str = "isTabularPartOf"
REL_MAPS_TO_DB_TABLE: str = "mapsToDbTable"
REL_REFERS_TO_OBJECT: str = "refersToObject"
REL_IS_REFERENCED_BY_OBJECT: str = "isReferencedByObject"

_ALL_RELATIONS: frozenset[str] = frozenset({
    REL_HAS_TABULAR_PART,
    REL_IS_TABULAR_PART_OF,
    REL_MAPS_TO_DB_TABLE,
    REL_REFERS_TO_OBJECT,
    REL_IS_REFERENCED_BY_OBJECT,
})


def build_relationships_workunit(
    *,
    entity_urn: str,
    entity_type: str,
    relationships: Mapping[str, Sequence[str]],
    workunit_id: str | None = None,
) -> MetadataWorkUnit:
    """:raises ValueError: если все ``relationships`` пусты."""
    payload: dict[str, Any] = {}
    for key, urns in relationships.items():
        if key not in _ALL_RELATIONS:
            raise ValueError(
                f"unknown oneCDomainRelationships field: {key!r}; "
                f"expected one of {sorted(_ALL_RELATIONS)}"
            )
        cleaned = [u for u in urns if u]
        if cleaned:
            payload[key] = cleaned

    if not payload:
        raise ValueError(
            "relationships workunit must contain at least one non-empty field; "
            "use config flags to skip the emission instead"
        )

    return build_custom_aspect_workunit(
        entity_urn=entity_urn,
        entity_type=entity_type,
        aspect_name=ONE_C_DOMAIN_RELATIONSHIPS,
        payload=payload,
        workunit_id=workunit_id or f"{entity_urn}-{ONE_C_DOMAIN_RELATIONSHIPS}",
    )


@dataclass
class DomainRelationshipsAccumulator:
    """Аккумулятор ``oneCDomainRelationships`` per entity.

    Один UPSERT перезаписывает весь generic aspect, поэтому source сначала
    собирает все relationship-поля на entity и только потом эмитит payload.
    """

    _entity_types: dict[str, str] = field(default_factory=dict)
    _relationships: dict[str, dict[str, set[str]]] = field(default_factory=dict)

    def add(
        self,
        *,
        entity_urn: str,
        relationship: str,
        target_urn: str | None,
        entity_type: str = "dataset",
    ) -> None:
        """Добавить одну связь, пропуская пустой target."""
        if relationship not in _ALL_RELATIONS:
            raise ValueError(
                f"unknown oneCDomainRelationships field: {relationship!r}; "
                f"expected one of {sorted(_ALL_RELATIONS)}"
            )
        if not target_urn:
            return
        existing_type = self._entity_types.setdefault(entity_urn, entity_type)
        if existing_type != entity_type:
            raise ValueError(
                f"entity {entity_urn!r} already registered as {existing_type!r}, "
                f"cannot also register as {entity_type!r}"
            )
        rels = self._relationships.setdefault(entity_urn, {})
        rels.setdefault(relationship, set()).add(target_urn)

    def add_many(
        self,
        *,
        entity_urn: str,
        relationship: str,
        target_urns: Iterable[str],
        entity_type: str = "dataset",
    ) -> None:
        """Добавить несколько targets в одно relationship-поле."""
        for target_urn in target_urns:
            self.add(
                entity_urn=entity_urn,
                relationship=relationship,
                target_urn=target_urn,
                entity_type=entity_type,
            )

    def workunits(self) -> Iterable[MetadataWorkUnit]:
        for entity_urn in sorted(self._relationships):
            rels = self._relationships[entity_urn]
            payload: dict[str, Sequence[str]] = {
                rel_name: sorted(targets)
                for rel_name, targets in sorted(rels.items())
                if targets
            }
            if not payload:
                continue
            yield build_relationships_workunit(
                entity_urn=entity_urn,
                entity_type=self._entity_types[entity_urn],
                relationships=payload,
            )
