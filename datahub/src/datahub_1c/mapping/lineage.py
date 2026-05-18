"""Эмиссия стандартного DataHub lineage.

1C API отдаёт dataset-level потоки данных через ``GET /lineage``:
``upstream_*`` описывает источник данных, ``downstream_*`` — объект, на
который нужно записать lineage.

Модуль сознательно не занимается резолвом UUID: source уже знает, какие
объекты реально вошли в текущий ingestion, и передаёт сюда готовые URN.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from datahub.emitter.mce_builder import (
    make_data_flow_urn,
    make_data_job_urn_with_flow,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    BrowsePathsV2Class,
    DataFlowInfoClass,
    DataJobInfoClass,
    DataJobInputOutputClass,
    DatasetLineageTypeClass,
    EdgeClass,
    StatusClass,
    UpstreamClass,
    UpstreamLineageClass,
)
from datahub.specific.dataset import DatasetPatchBuilder

from datahub_1c.api.models import LineageEdge
from datahub_1c.mapping.urn import PLATFORM_1C, validate_infobase_name

BASIS_LINEAGE_KIND = "basis"
REGISTER_MOVEMENT_LINEAGE_KIND = "register_movement"
MANUAL_DATASET_FLOW_LINEAGE_KIND = "manual_dataset_flow"
DIRECT_UPSTREAM_LINEAGE_KINDS: tuple[str, ...] = (
    BASIS_LINEAGE_KIND,
    MANUAL_DATASET_FLOW_LINEAGE_KIND,
)
PROCESS_LINEAGE_KINDS: tuple[str, ...] = (REGISTER_MOVEMENT_LINEAGE_KIND,)
SUPPORTED_LINEAGE_KINDS: tuple[str, ...] = (
    BASIS_LINEAGE_KIND,
    REGISTER_MOVEMENT_LINEAGE_KIND,
    MANUAL_DATASET_FLOW_LINEAGE_KIND,
)
ONEC_LINEAGE_MANAGED_BY_PROPERTY = "oneCLineageManagedBy"
ONEC_LINEAGE_MANAGED_BY_VALUE = "datahub-1c"
ONEC_LINEAGE_SCOPE_PROPERTY = "oneCLineageScope"
ONEC_DIRECT_LINEAGE_SCOPE = "direct_upstream"
DOCUMENT_OBJECT_TYPE_PLURAL = "Documents"
POSTING_JOB_ID = "posting"
POSTING_JOB_TYPE = "1C_DOCUMENT_POSTING"


@dataclass(frozen=True)
class LineageEmission:
    """Результат построения lineage workunit'ов."""

    workunits: tuple[MetadataWorkUnit, ...]
    edges_emitted: int
    edges_skipped: int
    owned_edges_removed: int = 0
    external_edges_preserved: int = 0


@dataclass(frozen=True)
class PostingProcessEmission:
    """Результат построения process-node lineage проведения документов."""

    workunits: tuple[MetadataWorkUnit, ...]
    document_keys_emitted: frozenset[tuple[str, str]]
    processes_emitted: int
    input_edges_emitted: int
    output_edges_emitted: int
    edges_skipped: int


@dataclass(frozen=True)
class PostingProcessRemovalEmission:
    """Результат построения tombstone workunit'ов для process-node lineage."""

    workunits: tuple[MetadataWorkUnit, ...]
    processes_removed: int


def build_upstream_lineage_workunits(
    *,
    edges: Iterable[LineageEdge],
    urn_by_object_key: Mapping[tuple[str, str], str],
    authoritative_downstream_urns: Iterable[str] = (),
    current_upstream_lineage_by_downstream_urn: Mapping[
        str,
        UpstreamLineageClass | None,
    ]
    | None = None,
) -> LineageEmission:
    """Сгруппировать ``LineageEdge`` и собрать patch-и ``UpstreamLineage``.

    ``authoritative_downstream_urns`` задаёт scope, в котором можно удалить
    старые 1С-owned direct edges, сохранив ручные и внешние связи.
    """
    grouped: dict[str, dict[str, dict[str, str]]] = {}
    skipped = 0

    for edge in edges:
        upstream_urn = urn_by_object_key.get(
            (
                edge.upstream_object_type,
                edge.upstream_name,
            )
        )
        downstream_urn = urn_by_object_key.get(
            (
                edge.downstream_object_type,
                edge.downstream_name,
            )
        )
        if upstream_urn is None or downstream_urn is None:
            skipped += 1
            continue

        upstreams = grouped.setdefault(downstream_urn, {})
        props = upstreams.setdefault(upstream_urn, _managed_direct_lineage_properties())
        _append_property_value(props, "lineageKinds", edge.kind)
        _append_property_value(props, "sources", edge.source)
        _append_property_value(props, "confidences", edge.confidence)
        if edge.description:
            _append_property_value(props, "descriptions", edge.description)
        if isinstance(edge.details, Mapping):
            origin = edge.details.get("origin")
            rule_id = edge.details.get("rule_id")
            if origin is not None:
                _append_property_value(props, "origins", str(origin))
            if rule_id is not None:
                _append_property_value(props, "ruleIds", str(rule_id))

    for downstream_urn in authoritative_downstream_urns:
        grouped.setdefault(downstream_urn, {})

    current_by_downstream = current_upstream_lineage_by_downstream_urn or {}
    workunits: list[MetadataWorkUnit] = []
    emitted_edges = 0
    removed_edges = 0
    preserved_external_edges = 0
    for downstream_urn, upstreams in sorted(grouped.items()):
        current_upstreams = _current_upstreams_by_dataset(
            current_by_downstream.get(downstream_urn)
        )
        stale_owned_upstream_urns = {
            upstream_urn
            for upstream_urn, upstream in current_upstreams.items()
            if _is_onec_owned_direct_upstream(upstream) and upstream_urn not in upstreams
        }
        upstream_classes_to_add: list[UpstreamClass] = []
        for upstream_urn, props in sorted(upstreams.items()):
            current_upstream = current_upstreams.get(upstream_urn)
            if current_upstream is not None and not _is_onec_owned_direct_upstream(
                current_upstream
            ):
                preserved_external_edges += 1
                continue
            upstream_classes_to_add.append(
                UpstreamClass(
                    dataset=upstream_urn,
                    type=DatasetLineageTypeClass.TRANSFORMED,
                    properties=props or None,
                )
            )
            emitted_edges += 1

        if stale_owned_upstream_urns or upstream_classes_to_add:
            patch_builder = DatasetPatchBuilder(downstream_urn)
            for upstream_urn in sorted(stale_owned_upstream_urns):
                patch_builder.remove_upstream_lineage(upstream_urn)
                removed_edges += 1
            for upstream in upstream_classes_to_add:
                patch_builder.add_upstream_lineage(upstream)
            workunits.extend(_patch_builder_workunits(patch_builder))

    return LineageEmission(
        workunits=tuple(workunits),
        edges_emitted=emitted_edges,
        edges_skipped=skipped,
        owned_edges_removed=removed_edges,
        external_edges_preserved=preserved_external_edges,
    )


def build_posting_process_lineage_workunits(
    *,
    edges: Iterable[LineageEdge],
    urn_by_object_key: Mapping[tuple[str, str], str],
    object_uuid_by_object_key: Mapping[tuple[str, str], str],
    object_full_name_by_key: Mapping[tuple[str, str], str],
    tabular_urn_by_object_key: Mapping[tuple[str, str, str], str],
    infobase_name: str,
    env: str,
) -> PostingProcessEmission:
    """Построить ``DataFlow`` / ``DataJob`` lineage для проведения документов.

    ``register_movement`` в 1С описывает не прямой поток ``Document -> Register``,
    а процесс проведения документа. Для каждого типа документа создаём отдельный
    ``DataFlow`` и один стабильный ``DataJob`` ``posting``. Входы job-а: главный
    dataset документа и все его эмитимые табличные части. Выходы: регистры из
    ``register_movement`` edges.
    """
    processes: dict[tuple[str, str], _PostingProcessBuilder] = {}
    skipped = 0

    for edge in edges:
        if edge.kind != REGISTER_MOVEMENT_LINEAGE_KIND:
            continue
        document_key = (edge.upstream_object_type, edge.upstream_name)
        output_key = (edge.downstream_object_type, edge.downstream_name)

        if edge.upstream_object_type != DOCUMENT_OBJECT_TYPE_PLURAL:
            skipped += 1
            continue

        document_urn = urn_by_object_key.get(document_key)
        document_uuid = object_uuid_by_object_key.get(document_key)
        output_urn = urn_by_object_key.get(output_key)
        if document_urn is None or document_uuid is None or output_urn is None:
            skipped += 1
            continue

        builder = processes.setdefault(
            document_key,
            _PostingProcessBuilder(
                document_key=document_key,
                document_urn=document_urn,
                document_uuid=document_uuid,
                document_full_name=(
                    object_full_name_by_key.get(document_key) or f"Документ.{edge.upstream_name}"
                ),
            ),
        )
        builder.add_register_output(edge=edge, output_urn=output_urn)

    workunits: list[MetadataWorkUnit] = []
    input_edges_emitted = 0
    output_edges_emitted = 0
    processes_emitted = 0
    for document_key, builder in sorted(processes.items()):
        tabular_inputs = _tabular_inputs_for_document(
            document_key=document_key,
            tabular_urn_by_object_key=tabular_urn_by_object_key,
        )
        process_wus, input_count, output_count = _build_posting_process_workunits(
            builder=builder,
            tabular_inputs=tabular_inputs,
            infobase_name=infobase_name,
            env=env,
        )
        workunits.extend(process_wus)
        input_edges_emitted += input_count
        output_edges_emitted += output_count
        processes_emitted += 1

    return PostingProcessEmission(
        workunits=tuple(workunits),
        document_keys_emitted=frozenset(processes),
        processes_emitted=processes_emitted,
        input_edges_emitted=input_edges_emitted,
        output_edges_emitted=output_edges_emitted,
        edges_skipped=skipped,
    )


def build_removed_posting_process_workunits(
    *,
    object_uuid_by_object_key: Mapping[tuple[str, str], str],
    document_keys: Iterable[tuple[str, str]] | None = None,
    infobase_name: str,
    env: str,
) -> PostingProcessRemovalEmission:
    """Пометить posting-process nodes текущего scope как удалённые.

    Используется, когда recipe отключает ``register_movement`` через
    ``ingestion.lineage_kinds``. Иначе ранее эмитированные ``DataFlow`` /
    ``DataJob`` проведения остались бы stale в DataHub после фильтрации.
    """
    workunits: list[MetadataWorkUnit] = []
    processes_removed = 0
    keys = document_keys if document_keys is not None else object_uuid_by_object_key
    for object_type, object_name in sorted(keys):
        if object_type != DOCUMENT_OBJECT_TYPE_PLURAL:
            continue
        object_uuid = object_uuid_by_object_key.get((object_type, object_name))
        if object_uuid is None:
            continue
        flow_urn, job_urn = _posting_process_urns(
            document_uuid=object_uuid,
            infobase_name=infobase_name,
            env=env,
        )
        workunits.extend(
            [
                MetadataChangeProposalWrapper(
                    entityUrn=flow_urn,
                    aspect=StatusClass(removed=True),
                ).as_workunit(),
                MetadataChangeProposalWrapper(
                    entityUrn=job_urn,
                    aspect=StatusClass(removed=True),
                ).as_workunit(),
                MetadataChangeProposalWrapper(
                    entityUrn=job_urn,
                    aspect=DataJobInputOutputClass(
                        inputDatasets=[],
                        inputDatasetEdges=[],
                        outputDatasets=[],
                        outputDatasetEdges=[],
                    ),
                ).as_workunit(),
            ]
        )
        processes_removed += 1

    return PostingProcessRemovalEmission(
        workunits=tuple(workunits),
        processes_removed=processes_removed,
    )


@dataclass
class _PostingProcessBuilder:
    """Промежуточное состояние одного процесса проведения документа."""

    document_key: tuple[str, str]
    document_urn: str
    document_uuid: str
    document_full_name: str
    output_props_by_urn: dict[str, dict[str, str]] = field(default_factory=dict)
    input_props: dict[str, str] = field(
        default_factory=lambda: {
            "role": "document_main",
            "lineageKind": REGISTER_MOVEMENT_LINEAGE_KIND,
        }
    )

    def add_register_output(self, *, edge: LineageEdge, output_urn: str) -> None:
        _append_property_value(self.input_props, "sources", edge.source)
        _append_property_value(self.input_props, "confidences", edge.confidence)
        if edge.description:
            _append_property_value(self.input_props, "descriptions", edge.description)

        output_props = self.output_props_by_urn.setdefault(
            output_urn,
            {
                "role": "register_output",
                "lineageKind": REGISTER_MOVEMENT_LINEAGE_KIND,
            },
        )
        _append_property_value(output_props, "sources", edge.source)
        _append_property_value(output_props, "confidences", edge.confidence)
        if edge.description:
            _append_property_value(output_props, "descriptions", edge.description)


def _tabular_inputs_for_document(
    *,
    document_key: tuple[str, str],
    tabular_urn_by_object_key: Mapping[tuple[str, str, str], str],
) -> tuple[tuple[str, str], ...]:
    object_type, object_name = document_key
    return tuple(
        (ts_name, urn)
        for (ts_object_type, ts_object_name, ts_name), urn in sorted(
            tabular_urn_by_object_key.items()
        )
        if ts_object_type == object_type and ts_object_name == object_name
    )


def _build_posting_process_workunits(
    *,
    builder: _PostingProcessBuilder,
    tabular_inputs: tuple[tuple[str, str], ...],
    infobase_name: str,
    env: str,
) -> tuple[tuple[MetadataWorkUnit, ...], int, int]:
    infobase = validate_infobase_name(infobase_name)
    flow_urn, job_urn = _posting_process_urns(
        document_uuid=builder.document_uuid,
        infobase_name=infobase,
        env=env,
    )

    document_name = builder.document_key[1]
    flow_name = f"Проведение {builder.document_full_name}"
    job_name = flow_name

    input_edges = [
        EdgeClass(
            destinationUrn=builder.document_urn,
            properties=dict(builder.input_props),
        ),
    ]
    input_datasets = [builder.document_urn]
    for tabular_part_name, tabular_urn in tabular_inputs:
        input_datasets.append(tabular_urn)
        input_edges.append(
            EdgeClass(
                destinationUrn=tabular_urn,
                properties={
                    "role": "tabular_part",
                    "lineageKind": REGISTER_MOVEMENT_LINEAGE_KIND,
                    "sources": "metadata",
                    "confidences": "medium",
                    "tabularPart": tabular_part_name,
                    "inputSelection": "all_tabular_parts",
                },
            )
        )

    output_edges = [
        EdgeClass(destinationUrn=output_urn, properties=dict(props))
        for output_urn, props in sorted(builder.output_props_by_urn.items())
    ]
    output_datasets = [edge.destinationUrn for edge in output_edges]

    workunits = (
        MetadataChangeProposalWrapper(
            entityUrn=flow_urn,
            aspect=DataFlowInfoClass(
                name=flow_name,
                description=(
                    "Статический процесс проведения документа 1С. "
                    "Входы процесса — main dataset документа и все его "
                    "табличные части; выходы — регистры, в которые документ "
                    "делает движения."
                ),
                customProperties={
                    "processKind": "document_posting",
                    "infobaseName": infobase,
                    "documentObjectType": builder.document_key[0],
                    "documentName": document_name,
                    "documentFullName": builder.document_full_name,
                    "metadataUuid": builder.document_uuid,
                    "inputSelection": "all_tabular_parts",
                },
                env=env,
            ),
        ).as_workunit(),
        MetadataChangeProposalWrapper(
            entityUrn=flow_urn,
            aspect=StatusClass(removed=False),
        ).as_workunit(),
        # Process nodes are lineage-only helpers. Keep them searchable/lineage-visible,
        # but out of Navigate so they do not pollute the business 1C hierarchy.
        MetadataChangeProposalWrapper(
            entityUrn=flow_urn,
            aspect=BrowsePathsV2Class(path=[]),
        ).as_workunit(),
        MetadataChangeProposalWrapper(
            entityUrn=job_urn,
            aspect=DataJobInfoClass(
                name=job_name,
                type=POSTING_JOB_TYPE,
                description=f"Проведение {builder.document_full_name}",
                flowUrn=flow_urn,
                customProperties={
                    "processKind": "document_posting",
                    "infobaseName": infobase,
                    "documentObjectType": builder.document_key[0],
                    "documentName": document_name,
                    "documentFullName": builder.document_full_name,
                    "metadataUuid": builder.document_uuid,
                    "inputSelection": "all_tabular_parts",
                },
                env=env,
            ),
        ).as_workunit(),
        MetadataChangeProposalWrapper(
            entityUrn=job_urn,
            aspect=StatusClass(removed=False),
        ).as_workunit(),
        MetadataChangeProposalWrapper(
            entityUrn=job_urn,
            aspect=BrowsePathsV2Class(path=[]),
        ).as_workunit(),
        MetadataChangeProposalWrapper(
            entityUrn=job_urn,
            aspect=DataJobInputOutputClass(
                inputDatasets=input_datasets,
                inputDatasetEdges=input_edges,
                outputDatasets=output_datasets,
                outputDatasetEdges=output_edges,
            ),
        ).as_workunit(),
    )
    return workunits, len(input_edges), len(output_edges)


def _posting_process_urns(
    *,
    document_uuid: str,
    infobase_name: str,
    env: str,
) -> tuple[str, str]:
    infobase = validate_infobase_name(infobase_name)
    flow_id = f"{infobase}.posting.{document_uuid}"
    flow_urn = make_data_flow_urn(
        orchestrator=PLATFORM_1C,
        flow_id=flow_id,
        cluster=env,
    )
    job_urn = make_data_job_urn_with_flow(flow_urn, POSTING_JOB_ID)
    return flow_urn, job_urn


def _managed_direct_lineage_properties() -> dict[str, str]:
    """Служебные свойства, по которым повторный ingest узнаёт свои edges."""
    return {
        ONEC_LINEAGE_MANAGED_BY_PROPERTY: ONEC_LINEAGE_MANAGED_BY_VALUE,
        ONEC_LINEAGE_SCOPE_PROPERTY: ONEC_DIRECT_LINEAGE_SCOPE,
    }


def _current_upstreams_by_dataset(
    aspect: UpstreamLineageClass | None,
) -> dict[str, UpstreamClass]:
    """Индексировать текущие upstream edges по URN upstream dataset."""
    if aspect is None:
        return {}
    return {upstream.dataset: upstream for upstream in aspect.upstreams or []}


def _is_onec_owned_direct_upstream(upstream: UpstreamClass) -> bool:
    """Определить, принадлежит ли upstream edge 1С-коннектору.

    Новые записи распознаются по ``oneCLineageManagedBy=datahub-1c``. Для уже
    загруженных до этого изменения edges оставлен legacy-признак: значения ``basis`` и
    ``manual_dataset_flow`` в ``lineageKinds``. DataHub UI обычно не пишет такие
    свойства для ручных связей, поэтому эти edges остаются нетронутыми.
    """
    props = upstream.properties or {}
    if (
        props.get(ONEC_LINEAGE_MANAGED_BY_PROPERTY) == ONEC_LINEAGE_MANAGED_BY_VALUE
        and props.get(ONEC_LINEAGE_SCOPE_PROPERTY) == ONEC_DIRECT_LINEAGE_SCOPE
    ):
        return True

    lineage_kinds = set(_split_csv_property(props.get("lineageKinds")))
    return bool(lineage_kinds & set(DIRECT_UPSTREAM_LINEAGE_KINDS))


def _split_csv_property(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _patch_builder_workunits(patch_builder: DatasetPatchBuilder) -> list[MetadataWorkUnit]:
    """Преобразовать patch MCP из DataHub SDK в ``MetadataWorkUnit``."""
    return [
        MetadataWorkUnit(
            id=MetadataWorkUnit.generate_workunit_id(mcp),
            mcp_raw=mcp,
        )
        for mcp in patch_builder.build()
    ]


def _append_property_value(props: dict[str, str], key: str, value: str | None) -> None:
    """Добавить уникальное значение в comma-separated строку properties."""
    if not value:
        return
    current = props.get(key)
    if current is None:
        props[key] = value
        return
    values = current.split(",")
    if value not in values:
        values.append(value)
        props[key] = ",".join(values)
