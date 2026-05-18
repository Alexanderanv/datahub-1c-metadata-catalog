from __future__ import annotations

import json

from datahub.metadata.schema_classes import (
    BrowsePathsV2Class,
    DataFlowInfoClass,
    DataJobInfoClass,
    DataJobInputOutputClass,
    DatasetLineageTypeClass,
    StatusClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from datahub_1c.api.models import LineageEdge
from datahub_1c.mapping.lineage import (
    ONEC_DIRECT_LINEAGE_SCOPE,
    ONEC_LINEAGE_MANAGED_BY_PROPERTY,
    ONEC_LINEAGE_MANAGED_BY_VALUE,
    ONEC_LINEAGE_SCOPE_PROPERTY,
    build_posting_process_lineage_workunits,
    build_removed_posting_process_workunits,
    build_upstream_lineage_workunits,
)

INFOBASE = "1c-test"
DOC_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,1c-test.doc-uuid,DEV)"
DOC_TS_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,1c-test.doc-uuid.ts-uuid,DEV)"
REG_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,1c-test.reg-uuid,DEV)"
REG2_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,1c-test.reg2-uuid,DEV)"
CAT_URN = "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,1c-test.cat-uuid,DEV)"
DOC_UUID = "11111111-1111-1111-1111-111111111103"


def _patch_ops(wu) -> list[dict]:
    return json.loads(wu.metadata.aspect.value.decode("utf-8"))


def test_builds_upstream_lineage_on_downstream_dataset() -> None:
    emission = build_upstream_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Catalogs",
                upstream_name="Контрагенты",
                downstream_object_type="Documents",
                downstream_name="ЗаказКлиента",
                kind="basis",
                confidence="high",
            ),
        ],
        urn_by_object_key={
            ("Catalogs", "Контрагенты"): CAT_URN,
            ("Documents", "ЗаказКлиента"): DOC_URN,
        },
    )

    assert emission.edges_emitted == 1
    assert emission.edges_skipped == 0
    assert len(emission.workunits) == 1
    wu = emission.workunits[0]
    assert wu.metadata.entityUrn == DOC_URN
    assert wu.metadata.changeType == "PATCH"
    assert wu.metadata.aspectName == "upstreamLineage"
    ops = _patch_ops(wu)
    assert len(ops) == 1
    assert ops[0]["op"] == "add"
    assert ops[0]["path"] == f"/upstreams/{CAT_URN}"
    upstream = ops[0]["value"]
    assert upstream["dataset"] == CAT_URN
    assert upstream["type"] == "TRANSFORMED"
    assert upstream["properties"] == {
        ONEC_LINEAGE_MANAGED_BY_PROPERTY: ONEC_LINEAGE_MANAGED_BY_VALUE,
        ONEC_LINEAGE_SCOPE_PROPERTY: ONEC_DIRECT_LINEAGE_SCOPE,
        "lineageKinds": "basis",
        "sources": "metadata",
        "confidences": "high",
    }


def test_builds_manual_dataset_flow_as_upstream_lineage() -> None:
    emission = build_upstream_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Catalogs",
                upstream_name="Номенклатура",
                downstream_object_type="Documents",
                downstream_name="ЗаказКлиента",
                kind="manual_dataset_flow",
                source="manual",
                confidence="high",
                description="Ручная связь.",
                details={"origin": "extension_registry", "rule_id": "manual-rule-1"},
            ),
        ],
        urn_by_object_key={
            ("Catalogs", "Номенклатура"): CAT_URN,
            ("Documents", "ЗаказКлиента"): DOC_URN,
        },
    )

    assert emission.edges_emitted == 1
    upstream = _patch_ops(emission.workunits[0])[0]["value"]
    assert upstream["properties"] == {
        ONEC_LINEAGE_MANAGED_BY_PROPERTY: ONEC_LINEAGE_MANAGED_BY_VALUE,
        ONEC_LINEAGE_SCOPE_PROPERTY: ONEC_DIRECT_LINEAGE_SCOPE,
        "lineageKinds": "manual_dataset_flow",
        "sources": "manual",
        "confidences": "high",
        "descriptions": "Ручная связь.",
        "origins": "extension_registry",
        "ruleIds": "manual-rule-1",
    }


def test_removes_stale_owned_upstream_for_authoritative_downstreams() -> None:
    emission = build_upstream_lineage_workunits(
        edges=[],
        urn_by_object_key={("Documents", "ЗаказКлиента"): DOC_URN},
        authoritative_downstream_urns=[DOC_URN],
        current_upstream_lineage_by_downstream_urn={
            DOC_URN: UpstreamLineageClass(
                upstreams=[
                    UpstreamClass(
                        dataset=CAT_URN,
                        type=DatasetLineageTypeClass.TRANSFORMED,
                        properties={"lineageKinds": "basis"},
                    ),
                ]
            ),
        },
    )

    assert emission.edges_emitted == 0
    assert emission.owned_edges_removed == 1
    assert len(emission.workunits) == 1
    ops = _patch_ops(emission.workunits[0])
    assert ops == [{"op": "remove", "path": f"/upstreams/{CAT_URN}", "value": {}}]


def test_preserves_external_upstream_for_authoritative_downstreams() -> None:
    emission = build_upstream_lineage_workunits(
        edges=[],
        urn_by_object_key={("Documents", "ЗаказКлиента"): DOC_URN},
        authoritative_downstream_urns=[DOC_URN],
        current_upstream_lineage_by_downstream_urn={
            DOC_URN: UpstreamLineageClass(
                upstreams=[
                    UpstreamClass(
                        dataset=CAT_URN,
                        type=DatasetLineageTypeClass.TRANSFORMED,
                        properties={"externalSystem": "manual-ui"},
                    ),
                ]
            ),
        },
    )

    assert emission.edges_emitted == 0
    assert emission.owned_edges_removed == 0
    assert emission.workunits == ()


def test_does_not_overwrite_existing_external_edge_with_same_pair() -> None:
    emission = build_upstream_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Catalogs",
                upstream_name="Контрагенты",
                downstream_object_type="Documents",
                downstream_name="ЗаказКлиента",
                kind="basis",
            ),
        ],
        urn_by_object_key={
            ("Catalogs", "Контрагенты"): CAT_URN,
            ("Documents", "ЗаказКлиента"): DOC_URN,
        },
        authoritative_downstream_urns=[DOC_URN],
        current_upstream_lineage_by_downstream_urn={
            DOC_URN: UpstreamLineageClass(
                upstreams=[
                    UpstreamClass(
                        dataset=CAT_URN,
                        type=DatasetLineageTypeClass.TRANSFORMED,
                        properties={"externalSystem": "manual-ui"},
                    ),
                ]
            ),
        },
    )

    assert emission.edges_emitted == 0
    assert emission.external_edges_preserved == 1
    assert emission.workunits == ()


def test_merges_multiple_edges_to_same_upstream() -> None:
    emission = build_upstream_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="AccumulationRegisters",
                downstream_name="Продажи",
                kind="register_movement",
            ),
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="AccumulationRegisters",
                downstream_name="Продажи",
                kind="basis",
                confidence="high",
            ),
        ],
        urn_by_object_key={
            ("Documents", "ЗаказКлиента"): DOC_URN,
            ("AccumulationRegisters", "Продажи"): REG_URN,
        },
    )

    assert emission.edges_emitted == 1
    upstream = _patch_ops(emission.workunits[0])[0]["value"]
    assert upstream["properties"]["lineageKinds"] == "register_movement,basis"
    assert upstream["properties"]["confidences"] == "medium,high"


def test_skips_edges_with_missing_urns() -> None:
    emission = build_upstream_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Catalogs",
                upstream_name="Контрагенты",
                downstream_object_type="Documents",
                downstream_name="ЗаказКлиента",
                kind="basis",
            ),
        ],
        urn_by_object_key={("Documents", "ЗаказКлиента"): DOC_URN},
    )

    assert emission.edges_emitted == 0
    assert emission.edges_skipped == 1
    assert emission.workunits == ()


def test_builds_posting_process_with_document_tabular_parts_and_register_output() -> None:
    emission = build_posting_process_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="AccumulationRegisters",
                downstream_name="Продажи",
                kind="register_movement",
                source="metadata",
                confidence="medium",
            ),
        ],
        urn_by_object_key={
            ("Documents", "ЗаказКлиента"): DOC_URN,
            ("AccumulationRegisters", "Продажи"): REG_URN,
        },
        object_uuid_by_object_key={("Documents", "ЗаказКлиента"): DOC_UUID},
        object_full_name_by_key={
            ("Documents", "ЗаказКлиента"): "Документ.ЗаказКлиента",
        },
        tabular_urn_by_object_key={
            ("Documents", "ЗаказКлиента", "Товары"): DOC_TS_URN,
        },
        infobase_name=INFOBASE,
        env="DEV",
    )

    assert emission.processes_emitted == 1
    assert emission.input_edges_emitted == 2
    assert emission.output_edges_emitted == 1
    assert emission.edges_skipped == 0
    assert len(emission.workunits) == 7

    aspects = [wu.metadata.aspect for wu in emission.workunits]
    assert isinstance(aspects[0], DataFlowInfoClass)
    assert aspects[0].name == "Проведение Документ.ЗаказКлиента"
    assert aspects[0].customProperties["processKind"] == "document_posting"
    assert aspects[0].customProperties["infobaseName"] == INFOBASE
    assert aspects[0].customProperties["inputSelection"] == "all_tabular_parts"

    assert isinstance(aspects[2], BrowsePathsV2Class)
    assert aspects[2].path == []

    assert isinstance(aspects[3], DataJobInfoClass)
    assert aspects[3].name == "Проведение Документ.ЗаказКлиента"
    assert aspects[3].flowUrn == emission.workunits[0].metadata.entityUrn

    assert isinstance(aspects[5], BrowsePathsV2Class)
    assert aspects[5].path == []

    assert isinstance(aspects[6], DataJobInputOutputClass)
    io = aspects[6]
    assert io.inputDatasets == [DOC_URN, DOC_TS_URN]
    assert io.outputDatasets == [REG_URN]
    assert io.inputDatasetEdges[0].destinationUrn == DOC_URN
    assert io.inputDatasetEdges[0].properties["role"] == "document_main"
    assert io.inputDatasetEdges[1].destinationUrn == DOC_TS_URN
    assert io.inputDatasetEdges[1].properties == {
        "role": "tabular_part",
        "lineageKind": "register_movement",
        "sources": "metadata",
        "confidences": "medium",
        "tabularPart": "Товары",
        "inputSelection": "all_tabular_parts",
    }
    assert io.outputDatasetEdges[0].destinationUrn == REG_URN
    assert io.outputDatasetEdges[0].properties["role"] == "register_output"
    assert io.outputDatasetEdges[0].properties["lineageKind"] == "register_movement"


def test_posting_process_skips_non_document_or_missing_urn_edges() -> None:
    emission = build_posting_process_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Catalogs",
                upstream_name="Контрагенты",
                downstream_object_type="AccumulationRegisters",
                downstream_name="Продажи",
                kind="register_movement",
            ),
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="AccumulationRegisters",
                downstream_name="Продажи",
                kind="register_movement",
            ),
        ],
        urn_by_object_key={("Documents", "ЗаказКлиента"): DOC_URN},
        object_uuid_by_object_key={("Documents", "ЗаказКлиента"): DOC_UUID},
        object_full_name_by_key={},
        tabular_urn_by_object_key={},
        infobase_name=INFOBASE,
        env="DEV",
    )

    assert emission.processes_emitted == 0
    assert emission.edges_skipped == 2
    assert emission.workunits == ()


def test_posting_process_groups_multiple_register_outputs_for_same_document() -> None:
    emission = build_posting_process_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="AccumulationRegisters",
                downstream_name="Продажи",
                kind="register_movement",
            ),
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="InformationRegisters",
                downstream_name="Цены",
                kind="register_movement",
            ),
        ],
        urn_by_object_key={
            ("Documents", "ЗаказКлиента"): DOC_URN,
            ("AccumulationRegisters", "Продажи"): REG_URN,
            ("InformationRegisters", "Цены"): REG2_URN,
        },
        object_uuid_by_object_key={("Documents", "ЗаказКлиента"): DOC_UUID},
        object_full_name_by_key={
            ("Documents", "ЗаказКлиента"): "Документ.ЗаказКлиента",
        },
        tabular_urn_by_object_key={},
        infobase_name=INFOBASE,
        env="DEV",
    )

    assert emission.processes_emitted == 1
    assert emission.output_edges_emitted == 2
    io = emission.workunits[-1].metadata.aspect
    assert isinstance(io, DataJobInputOutputClass)
    assert io.outputDatasets == [REG_URN, REG2_URN]


def test_posting_process_accepts_accounting_and_calculation_register_outputs() -> None:
    emission = build_posting_process_lineage_workunits(
        edges=[
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="AccountingRegisters",
                downstream_name="Управленческий",
                kind="register_movement",
            ),
            LineageEdge(
                upstream_object_type="Documents",
                upstream_name="ЗаказКлиента",
                downstream_object_type="CalculationRegisters",
                downstream_name="Начисления",
                kind="register_movement",
            ),
        ],
        urn_by_object_key={
            ("Documents", "ЗаказКлиента"): DOC_URN,
            ("AccountingRegisters", "Управленческий"): REG_URN,
            ("CalculationRegisters", "Начисления"): REG2_URN,
        },
        object_uuid_by_object_key={("Documents", "ЗаказКлиента"): DOC_UUID},
        object_full_name_by_key={
            ("Documents", "ЗаказКлиента"): "Документ.ЗаказКлиента",
        },
        tabular_urn_by_object_key={},
        infobase_name=INFOBASE,
        env="DEV",
    )

    assert emission.processes_emitted == 1
    assert emission.output_edges_emitted == 2
    io = emission.workunits[-1].metadata.aspect
    assert isinstance(io, DataJobInputOutputClass)
    assert io.outputDatasets == [REG_URN, REG2_URN]


def test_removed_posting_process_tombstones_document_process_nodes() -> None:
    emission = build_removed_posting_process_workunits(
        object_uuid_by_object_key={
            ("Documents", "ЗаказКлиента"): DOC_UUID,
            ("Catalogs", "Номенклатура"): "cat-uuid",
        },
        infobase_name=INFOBASE,
        env="DEV",
    )

    assert emission.processes_removed == 1
    assert len(emission.workunits) == 3
    aspects = [wu.metadata.aspect for wu in emission.workunits]
    assert isinstance(aspects[0], StatusClass)
    assert aspects[0].removed is True
    assert isinstance(aspects[1], StatusClass)
    assert aspects[1].removed is True
    assert isinstance(aspects[2], DataJobInputOutputClass)
    assert aspects[2].inputDatasets == []
    assert aspects[2].outputDatasets == []
    assert "posting" in emission.workunits[1].metadata.entityUrn


def test_removed_posting_process_can_target_subset_of_documents() -> None:
    emission = build_removed_posting_process_workunits(
        object_uuid_by_object_key={
            ("Documents", "ЗаказКлиента"): DOC_UUID,
            ("Documents", "ПоступлениеТоваров"): "22222222-2222-2222-2222-222222222222",
        },
        document_keys=[("Documents", "ЗаказКлиента")],
        infobase_name=INFOBASE,
        env="DEV",
    )

    assert emission.processes_removed == 1
    urns = [wu.metadata.entityUrn for wu in emission.workunits]
    assert all(DOC_UUID in urn for urn in urns)
