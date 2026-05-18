from __future__ import annotations

import json

import pytest

from datahub_1c.mapping.custom_aspects import ONE_C_DOMAIN_RELATIONSHIPS
from datahub_1c.mapping.relationships import (
    REL_HAS_TABULAR_PART,
    REL_IS_REFERENCED_BY_OBJECT,
    REL_IS_TABULAR_PART_OF,
    REL_MAPS_TO_DB_TABLE,
    REL_REFERS_TO_OBJECT,
    DomainRelationshipsAccumulator,
    build_relationships_workunit,
)

PARENT_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.X,PROD)"
TP_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,Document.X.TP,PROD)"


class TestBuildRelationshipsWorkunit:
    def test_has_tabular_part(self) -> None:
        wu = build_relationships_workunit(
            entity_urn=PARENT_URN,
            entity_type="dataset",
            relationships={REL_HAS_TABULAR_PART: [TP_URN]},
        )
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload == {REL_HAS_TABULAR_PART: [TP_URN]}
        assert wu.metadata.aspectName == ONE_C_DOMAIN_RELATIONSHIPS

    def test_is_tabular_part_of(self) -> None:
        wu = build_relationships_workunit(
            entity_urn=TP_URN,
            entity_type="dataset",
            relationships={REL_IS_TABULAR_PART_OF: [PARENT_URN]},
        )
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload[REL_IS_TABULAR_PART_OF] == [PARENT_URN]

    def test_multiple_keys_in_single_payload(self) -> None:
        wu = build_relationships_workunit(
            entity_urn=PARENT_URN,
            entity_type="dataset",
            relationships={
                REL_HAS_TABULAR_PART: [TP_URN],
                REL_MAPS_TO_DB_TABLE: ["urn:li:dataset:(urn:li:dataPlatform:postgres,t,PROD)"],
            },
        )
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert set(payload.keys()) == {REL_HAS_TABULAR_PART, REL_MAPS_TO_DB_TABLE}

    def test_empty_lists_are_filtered_out(self) -> None:
        wu = build_relationships_workunit(
            entity_urn=PARENT_URN,
            entity_type="dataset",
            relationships={
                REL_HAS_TABULAR_PART: [TP_URN],
                REL_REFERS_TO_OBJECT: [],
                REL_IS_REFERENCED_BY_OBJECT: [""],  # пустые строки тоже отбрасываются
            },
        )
        payload = json.loads(wu.metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert list(payload.keys()) == [REL_HAS_TABULAR_PART]

    def test_all_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one non-empty field"):
            build_relationships_workunit(
                entity_urn=PARENT_URN,
                entity_type="dataset",
                relationships={REL_HAS_TABULAR_PART: []},
            )

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown oneCDomainRelationships field"):
            build_relationships_workunit(
                entity_urn=PARENT_URN,
                entity_type="dataset",
                relationships={"hasChildrenFriends": [TP_URN]},
            )

    def test_default_workunit_id(self) -> None:
        wu = build_relationships_workunit(
            entity_urn=PARENT_URN,
            entity_type="dataset",
            relationships={REL_HAS_TABULAR_PART: [TP_URN]},
        )
        assert wu.id == f"{PARENT_URN}-{ONE_C_DOMAIN_RELATIONSHIPS}"


class TestDomainRelationshipsAccumulator:
    def test_merges_multiple_relationship_fields_for_same_entity(self) -> None:
        acc = DomainRelationshipsAccumulator()
        pg_urn = "urn:li:dataset:(urn:li:dataPlatform:postgres,t,PROD)"
        acc.add(
            entity_urn=PARENT_URN,
            relationship=REL_HAS_TABULAR_PART,
            target_urn=TP_URN,
        )
        acc.add(
            entity_urn=PARENT_URN,
            relationship=REL_MAPS_TO_DB_TABLE,
            target_urn=pg_urn,
        )
        acc.add(
            entity_urn=PARENT_URN,
            relationship=REL_HAS_TABULAR_PART,
            target_urn=TP_URN,
        )

        wus = list(acc.workunits())
        assert len(wus) == 1
        payload = json.loads(wus[0].metadata.aspect.value.decode("ascii"))  # type: ignore[union-attr]
        assert payload == {
            REL_HAS_TABULAR_PART: [TP_URN],
            REL_MAPS_TO_DB_TABLE: [pg_urn],
        }

    def test_emits_one_workunit_per_entity(self) -> None:
        acc = DomainRelationshipsAccumulator()
        acc.add(
            entity_urn=PARENT_URN,
            relationship=REL_HAS_TABULAR_PART,
            target_urn=TP_URN,
        )
        acc.add(
            entity_urn=TP_URN,
            relationship=REL_IS_TABULAR_PART_OF,
            target_urn=PARENT_URN,
        )

        wus = list(acc.workunits())
        assert len(wus) == 2
        assert {wu.metadata.entityUrn for wu in wus} == {PARENT_URN, TP_URN}

    def test_unknown_relationship_is_rejected(self) -> None:
        acc = DomainRelationshipsAccumulator()
        with pytest.raises(ValueError, match="unknown oneCDomainRelationships field"):
            acc.add(
                entity_urn=PARENT_URN,
                relationship="surprisesEveryone",
                target_urn=TP_URN,
            )
