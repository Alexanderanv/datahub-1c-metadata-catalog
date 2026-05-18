"""DataHub ``Source`` для платформы ``1c-enterprise``.

Источник читает сервис метаданных 1С, эмитит datasets/containers/schemaMetadata,
кастомные аспекты oneC*, связи с физическими DB-таблицами, lineage и доменные
reference-связи. Детальная раскладка по аспектам живёт в модулях
``datahub_1c.mapping``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Self
from urllib.parse import urlencode

import requests
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.api.source import MetadataWorkUnitProcessor, SourceReport
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.ingestion.source.state.stale_entity_removal_handler import (
    StaleEntityRemovalHandler,
    StaleEntityRemovalSourceReport,
)
from datahub.ingestion.source.state.stateful_ingestion_base import (
    StatefulIngestionSourceBase,
)
from datahub.metadata.schema_classes import UpstreamLineageClass
from datahub.utilities.urns.urn import guess_entity_type

from datahub_1c.api.client import OneCApiClient
from datahub_1c.api.models import (
    TABLE_PURPOSE_MAIN,
    TABLE_PURPOSE_TABULAR_SECTION,
    TABLE_PURPOSE_TOTALS,
    TABLE_PURPOSE_TOTALS_SLICE_FIRST,
    TABLE_PURPOSE_TOTALS_SLICE_LAST,
    DbMapping,
    DbTableMapping,
    IntegrationService,
    LineageEdge,
    MetadataObjectDetail,
    MetadataObjectSummary,
    Reference,
    TabularPart,
)
from datahub_1c.config import OneCSourceConfig
from datahub_1c.mapping.containers import (
    build_container_urn,
    build_container_workunits,
    build_infobase_workunits,
    build_type_folder_workunits,
)
from datahub_1c.mapping.custom_aspects import (
    ONE_C_CATALOG_PROPERTIES,
    ONE_C_DB_MAPPING,
    ONE_C_DOCUMENT_PROPERTIES,
    ONE_C_DOMAIN_RELATIONSHIPS,
    ONE_C_OBJECT_PROPERTIES,
    ONE_C_REGISTER_PROPERTIES,
)
from datahub_1c.mapping.datasets import build_dataset_workunits
from datahub_1c.mapping.db_mapping import (
    build_db_mapping_aspect_wu,
    build_pg_dataset_workunits,
    build_siblings_workunits,
    is_siblable_purpose,
)
from datahub_1c.mapping.integration_services import (
    build_integration_service_type_folder_workunits,
    build_integration_service_workunits,
)
from datahub_1c.mapping.kind_properties import (
    build_catalog_properties_workunit,
    build_document_properties_workunit,
    build_register_properties_workunit,
    register_kind_value_for,
)
from datahub_1c.mapping.lineage import (
    DIRECT_UPSTREAM_LINEAGE_KINDS,
    DOCUMENT_OBJECT_TYPE_PLURAL,
    REGISTER_MOVEMENT_LINEAGE_KIND,
    build_posting_process_lineage_workunits,
    build_removed_posting_process_workunits,
    build_upstream_lineage_workunits,
)
from datahub_1c.mapping.metadata_uuid import (
    MetadataUuidIndex,
    parse_config_dump_info,
)
from datahub_1c.mapping.platform import build_platform_workunit
from datahub_1c.mapping.relationships import (
    REL_HAS_TABULAR_PART,
    REL_IS_REFERENCED_BY_OBJECT,
    REL_IS_TABULAR_PART_OF,
    REL_MAPS_TO_DB_TABLE,
    REL_REFERS_TO_OBJECT,
    DomainRelationshipsAccumulator,
)
from datahub_1c.mapping.schema_fields import build_schema_metadata_workunit
from datahub_1c.mapping.tabular_parts import build_tabular_part_emission
from datahub_1c.mapping.translit import transliterate
from datahub_1c.mapping.urn import (
    ObjectKind,
    _legacy_translit_dataset_name,
    dataset_urn,
    display_full_name,
    infobase_container_urn_for,
    kind_from_plural,
    spec_for,
    type_folder_container_urn_for,
)

logger = logging.getLogger(__name__)

LINEAGE_FILTER_QUERY_CHAR_LIMIT = 8_000


# Имена всех кастомных aspect'ов. Используется для фильтрации workunit'ов,
# если в recipe включён флаг `ingestion.emit_custom_aspects=false` —
# например, до развёртывания `custom-models.zip` в GMS, когда
# неизвестные aspect'ы ронят весь batch с HTTP 422.
_CUSTOM_ASPECT_NAMES: frozenset[str] = frozenset(
    {
        ONE_C_OBJECT_PROPERTIES,
        ONE_C_CATALOG_PROPERTIES,
        ONE_C_DOCUMENT_PROPERTIES,
        ONE_C_REGISTER_PROPERTIES,
        ONE_C_DB_MAPPING,
        ONE_C_DOMAIN_RELATIONSHIPS,
    }
)

# Все валидные значения `DbTableMapping.purpose`, которые мы умеем
# обрабатывать. Если в ответе /db-mapping встретится что-то не из
# этого списка (форвард-совместимость с расширением API), коннектор
# пропустит таблицу с предупреждением, а не упадёт.
_KNOWN_TABLE_PURPOSES: frozenset[str] = frozenset(
    {
        TABLE_PURPOSE_MAIN,
        TABLE_PURPOSE_TABULAR_SECTION,
        TABLE_PURPOSE_TOTALS,
        TABLE_PURPOSE_TOTALS_SLICE_FIRST,
        TABLE_PURPOSE_TOTALS_SLICE_LAST,
    }
)


@dataclass
class OneCSourceReport(StaleEntityRemovalSourceReport):
    """Расширение ``SourceReport`` счётчиками, специфичными для 1С."""

    objects_fetched: int = 0
    objects_emitted: int = 0
    objects_filtered: int = 0
    objects_skipped_unknown_kind: int = 0
    objects_skipped_missing_uuid: int = 0  # объект не найден в ConfigDumpInfo.xml
    tabular_parts_skipped_missing_uuid: int = 0  # ТЧ не найдена в ConfigDumpInfo.xml
    attributes_missing_uuid: int = 0  # реквизит не найден (warning, не блокирует)
    infobases_emitted: int = 0
    type_folders_emitted: int = 0
    containers_emitted: int = 0
    tabular_parts_emitted: int = 0
    schema_metadata_emitted: int = 0
    kind_properties_emitted: int = 0
    pg_datasets_emitted: int = 0  # Main + вспомогательные (ТЧ/Totals/...)
    pg_aux_datasets_emitted: int = 0  # вспомогательные таблицы без 1С DB mapping
    db_mappings_emitted: int = 0  # siblable DB mappings: oneCDbMapping + mapsToDbTable
    db_mapping_not_found: int = 0
    db_mapping_unknown_purpose_skipped: int = 0
    lineage_edges_fetched: int = 0
    lineage_edges_emitted: int = 0
    lineage_edges_skipped: int = 0
    lineage_owned_edges_removed: int = 0
    lineage_external_edges_preserved: int = 0
    lineage_edges_skipped_unsupported_kind: int = 0
    lineage_processes_emitted: int = 0
    lineage_processes_removed: int = 0
    lineage_process_input_edges_emitted: int = 0
    lineage_process_output_edges_emitted: int = 0
    reference_edges_fetched: int = 0
    reference_edges_emitted: int = 0
    reference_edges_skipped: int = 0
    reference_edges_skipped_missing_source: int = 0
    reference_edges_skipped_missing_target: int = 0
    integration_services_fetched: int = 0
    integration_services_emitted: int = 0
    integration_services_skipped_filtered: int = 0
    integration_services_skipped_missing_uuid: int = 0
    integration_service_type_folders_emitted: int = 0
    integration_endpoints_emitted: int = 0
    integration_endpoints_skipped_missing_uuid: int = 0
    integration_internal_inputs_resolved: int = 0
    integration_internal_inputs_unresolved: int = 0
    filtered_object_names: list[str] = field(default_factory=list)
    metadata_uuid_index_objects: int = 0  # сколько объектов в загруженном индексе


@dataclass(frozen=True)
class _ScopedObject:
    """Объект 1С, прошедший recipe-фильтры и UUID-preflight."""

    kind: ObjectKind
    summary: MetadataObjectSummary
    object_uuid: str
    tabular_parts: tuple[TabularPart, ...]
    tabular_section_uuid_by_name: Mapping[str, str]


@dataclass(frozen=True)
class _ScopedIntegrationService:
    """HTTP/Web-сервис 1С, прошедший recipe-фильтры и UUID-preflight."""

    service: IntegrationService
    service_uuid: str
    endpoint_uuid_by_full_name: Mapping[str, str]


class OneCSource(StatefulIngestionSourceBase):
    platform: str = "1c-enterprise"

    def __init__(
        self,
        config: OneCSourceConfig,
        ctx: PipelineContext,
        *,
        api_client: OneCApiClient | None = None,
        metadata_uuid_index: MetadataUuidIndex | None = None,
    ) -> None:
        super().__init__(config, ctx)
        self.config = config
        self.report = OneCSourceReport()
        self._client = api_client or OneCApiClient(
            base_url=str(config.base_url),
            username=config.username,
            password=config.password.get_secret_value(),
        )
        # Индекс можно подменить в тестах, чтобы не читать XML с диска.
        if metadata_uuid_index is not None:
            self._uuid_index = metadata_uuid_index
        else:
            path = config.metadata_uuid_source.config_dump_info_path
            logger.info("Loading metadata UUID index from %s", path)
            self._uuid_index = parse_config_dump_info(path)
        self.report.metadata_uuid_index_objects = len(self._uuid_index.objects)
        # Корневые type-folder контейнеры эмитятся один раз на вид за прогон.
        self._emitted_type_folders: set[ObjectKind] = set()
        self._emitted_integration_service_type_folders: set[str] = set()
        self._infobase_emitted = False
        self._stale_entity_removal_handler: StaleEntityRemovalHandler | None = None

    @classmethod
    def create(cls, config_dict: dict[str, Any], ctx: PipelineContext) -> Self:
        config = OneCSourceConfig.model_validate(config_dict)
        return cls(config, ctx)

    def get_report(self) -> SourceReport:
        return self.report

    def close(self) -> None:
        self._client.close()
        super().close()

    def get_workunit_processors(self) -> list[MetadataWorkUnitProcessor | None]:
        """Подключить контролируемую очистку для сущностей 1С.

        Физические DB datasets не входят в ownership 1С-source, поэтому
        stale cleanup фильтруется по URN текущей ИБ и env.
        """
        stale_handler = self._get_stale_entity_removal_handler()
        return [
            *super().get_workunit_processors(),
            self._one_c_owned_stale_entity_processor(stale_handler),
        ]

    def _get_stale_entity_removal_handler(self) -> StaleEntityRemovalHandler:
        if self._stale_entity_removal_handler is not None:
            return self._stale_entity_removal_handler

        stale_handler = StaleEntityRemovalHandler.create(self, self.config, self.ctx)
        default_job_id = stale_handler.job_id
        # Один pipeline может грузить несколько ИБ/окружений. Уникальный job id
        # не даёт state одной ИБ удалить сущности другой ИБ.
        stale_handler.set_job_id(f"{self.config.infobase.name}_{self.config.env}")
        # Handler регистрируется до смены job id; дефолтную запись убираем.
        if default_job_id != stale_handler.job_id:
            self.state_provider._usecase_handlers.pop(default_job_id, None)
        self.state_provider.register_stateful_ingestion_usecase_handler(stale_handler)
        self._stale_entity_removal_handler = stale_handler
        return stale_handler

    def _one_c_owned_stale_entity_processor(
        self,
        stale_handler: StaleEntityRemovalHandler,
    ) -> MetadataWorkUnitProcessor:
        def processor(stream: Iterable[MetadataWorkUnit]) -> Iterable[MetadataWorkUnit]:
            for wu in stream:
                urn = wu.get_urn()
                if wu.is_primary_source and self._is_stateful_cleanup_owned_urn(urn):
                    entity_type = guess_entity_type(urn)
                    if entity_type is not None:
                        stale_handler.add_entity_to_state(entity_type, urn)
                elif urn:
                    stale_handler.add_urn_to_skip(urn)
                yield wu

            yield from stale_handler.gen_removed_entity_workunits()

        return processor

    def _is_stateful_cleanup_owned_urn(self, urn: str | None) -> bool:
        """True для сущностей, жизненный цикл которых принадлежит этому source."""
        if not urn:
            return False

        infobase = self.config.infobase.name
        env = self.config.env

        if urn.startswith(
            f"urn:li:dataset:(urn:li:dataPlatform:{self.platform},{infobase}."
        ) and urn.endswith(f",{env})"):
            return True

        if urn == f"urn:li:container:infobase:{infobase}:{env}":
            return True
        if urn.startswith(f"urn:li:container:{infobase}:") and urn.endswith(f":{env}"):
            return True

        dataflow_prefix = f"urn:li:dataFlow:({self.platform},{infobase}."
        if urn.startswith(dataflow_prefix) and urn.endswith(f",{env})"):
            return True

        if urn.startswith("urn:li:dataJob:(") and dataflow_prefix in urn and (
            f",{env})" in urn
        ):
            return True

        return False

    def get_workunits_internal(self) -> Iterable[MetadataWorkUnit]:
        """Оркестратор ingestion: platform → (per-object) full emission."""
        emit_custom = self.config.ingestion.emit_custom_aspects

        def _filter(wu: MetadataWorkUnit) -> bool:
            """Отфильтровать oneC* aspects при ``emit_custom_aspects=false``."""
            if emit_custom:
                return True
            mcp = wu.metadata
            aspect_name = getattr(mcp, "aspectName", None)
            return aspect_name not in _CUSTOM_ASPECT_NAMES

        def _emit(wu_iter: Iterable[MetadataWorkUnit]) -> Iterable[MetadataWorkUnit]:
            for wu in wu_iter:
                if _filter(wu):
                    yield wu

        summaries = self._list_objects()
        self.report.objects_fetched = len(summaries)
        scoped_objects = self._validate_scoped_objects(summaries)
        scoped_integration_services: list[_ScopedIntegrationService] = []
        if self.config.integration_services.enabled:
            scoped_integration_services = self._validate_scoped_integration_services()

        yield from _emit([build_platform_workunit()])
        if not self._infobase_emitted:
            yield from _emit(
                build_infobase_workunits(
                    infobase_name=self.config.infobase.name,
                    display_name=self.config.infobase.display,
                    env=self.config.env,
                )
            )
            self._infobase_emitted = True
            self.report.infobases_emitted += 1

        lineage_object_full_names: list[str] = []
        lineage_urn_by_object_key: dict[tuple[str, str], str] = {}
        lineage_object_uuid_by_object_key: dict[tuple[str, str], str] = {}
        lineage_full_name_by_object_key: dict[tuple[str, str], str] = {}
        object_urn_by_full_name: dict[str, str] = {}
        tabular_urn_by_object_key: dict[tuple[str, str, str], str] = {}
        relationships = DomainRelationshipsAccumulator()

        for scoped in scoped_objects:
            kind = scoped.kind
            summary = scoped.summary
            object_uuid = scoped.object_uuid

            lineage_object_full_names.append(summary.full_name)
            object_key = (summary.object_type, summary.name)
            lineage_urn_by_object_key[object_key] = dataset_urn(
                infobase_name=self.config.infobase.name,
                object_uuid=object_uuid,
                env=self.config.env,
            )
            lineage_object_uuid_by_object_key[object_key] = object_uuid
            lineage_full_name_by_object_key[object_key] = display_full_name(
                kind,
                summary.name,
            )
            object_urn_by_full_name[summary.full_name] = lineage_urn_by_object_key[object_key]

            yield from _emit(
                self._emit_for_object(
                    kind,
                    summary,
                    object_uuid=object_uuid,
                    tabular_parts=scoped.tabular_parts,
                    tabular_section_uuid_by_name=scoped.tabular_section_uuid_by_name,
                    relationships=relationships,
                    tabular_urn_by_object_key=tabular_urn_by_object_key,
                )
            )

        if emit_custom and lineage_object_full_names:
            self._collect_reference_relationships(
                object_full_names=lineage_object_full_names,
                urn_by_object_key=lineage_urn_by_object_key,
                tabular_urn_by_object_key=tabular_urn_by_object_key,
                relationships=relationships,
            )
            yield from _emit(relationships.workunits())

        if scoped_integration_services:
            yield from _emit(
                self._emit_integration_services(
                    scoped_services=scoped_integration_services,
                    object_urn_by_full_name=object_urn_by_full_name,
                )
            )

        if self.config.ingestion.lineage and lineage_object_full_names:
            yield from _emit(
                self._emit_lineage(
                    object_full_names=lineage_object_full_names,
                    urn_by_object_key=lineage_urn_by_object_key,
                    object_uuid_by_object_key=lineage_object_uuid_by_object_key,
                    object_full_name_by_key=lineage_full_name_by_object_key,
                    tabular_urn_by_object_key=tabular_urn_by_object_key,
                )
            )

    def _validate_scoped_objects(
        self,
        summaries: Iterable[MetadataObjectSummary],
    ) -> list[_ScopedObject]:
        """Проверить UUID всех in-scope объектов и ТЧ до первой эмиссии.

        Если ``ConfigDumpInfo.xml`` не соответствует базе 1С, ingestion
        должен упасть до первого workunit.
        """
        result: list[_ScopedObject] = []
        for summary in summaries:
            kind = self._resolve_kind(summary)
            if kind is None:
                continue
            if not self.config.object_filters.includes_object(
                summary.object_type,
                summary.name,
            ):
                self.report.objects_filtered += 1
                continue

            object_uuid = self._uuid_index.object_uuid(kind, summary.name)
            if object_uuid is None:
                self.report.objects_skipped_missing_uuid += 1
                message = "object UUID not found in ConfigDumpInfo.xml"
                context = (
                    f"object={summary.full_name!r}, "
                    f"check that recipe.metadata_uuid_source.config_dump_info_path "
                    f"is in sync with the 1C configuration"
                )
                self.report.report_failure(
                    message=message,
                    context=context,
                )
                raise ValueError(f"{message}: {context}")

            tabular_parts = tuple(self._fetch_tabular_parts(kind, summary))
            tabular_section_uuid_by_name: dict[str, str] = {}
            for tp in tabular_parts:
                ts_uuid = self._uuid_index.tabular_section_uuid(
                    kind,
                    summary.name,
                    tp.name,
                )
                if ts_uuid is None:
                    self.report.tabular_parts_skipped_missing_uuid += 1
                    message = "tabular section UUID not found in ConfigDumpInfo.xml"
                    context = (
                        f"object={summary.full_name!r}, "
                        f"tabular_section={tp.name!r}, "
                        "check that ConfigDumpInfo.xml is in sync with the 1C configuration"
                    )
                    self.report.report_failure(
                        message=message,
                        context=context,
                    )
                    raise ValueError(f"{message}: {context}")
                tabular_section_uuid_by_name[tp.name] = ts_uuid

            result.append(
                _ScopedObject(
                    kind=kind,
                    summary=summary,
                    object_uuid=object_uuid,
                    tabular_parts=tabular_parts,
                    tabular_section_uuid_by_name=tabular_section_uuid_by_name,
                )
            )

        return result

    def _validate_scoped_integration_services(self) -> list[_ScopedIntegrationService]:
        """Проверить UUID HTTP/Web-сервисов и endpoints до первой эмиссии."""
        services = self._fetch_integration_services()
        self.report.integration_services_fetched = len(services)
        scope = self.config.integration_services
        result: list[_ScopedIntegrationService] = []

        for service in services:
            if not scope.includes_service(service.service_type, service.name):
                self.report.integration_services_skipped_filtered += 1
                continue

            endpoints = [
                endpoint
                for endpoint in service.endpoints
                if scope.includes_endpoint(
                    service.service_type,
                    service.name,
                    endpoint.full_name,
                )
            ]
            service = service.model_copy(update={"endpoints": endpoints})

            service_uuid = self._uuid_index.integration_service_uuid(
                service.service_type,
                service.name,
            )
            if service_uuid is None:
                self.report.integration_services_skipped_missing_uuid += 1
                message = "integration service UUID not found in ConfigDumpInfo.xml"
                context = f"service_type={service.service_type!r}, service={service.full_name!r}"
                self.report.report_failure(message=message, context=context)
                raise ValueError(f"{message}: {context}")

            endpoint_uuid_by_full_name: dict[str, str] = {}
            for endpoint in service.endpoints:
                endpoint_uuid = self._uuid_index.integration_endpoint_uuid(
                    endpoint.full_name,
                )
                if endpoint_uuid is None:
                    self.report.integration_endpoints_skipped_missing_uuid += 1
                    message = "integration endpoint UUID not found in ConfigDumpInfo.xml"
                    context = f"service={service.full_name!r}, endpoint={endpoint.full_name!r}"
                    self.report.report_failure(message=message, context=context)
                    raise ValueError(f"{message}: {context}")
                endpoint_uuid_by_full_name[endpoint.full_name] = endpoint_uuid

            result.append(
                _ScopedIntegrationService(
                    service=service,
                    service_uuid=service_uuid,
                    endpoint_uuid_by_full_name=endpoint_uuid_by_full_name,
                )
            )

        return result

    def _list_objects(self) -> list[MetadataObjectSummary]:
        types_filter = self.config.object_filters.include_types or None
        try:
            return self._client.list_objects(types=types_filter)
        except Exception as exc:
            self.report.report_failure(
                message="failed to fetch /objects",
                context=f"types={types_filter!r}",
                exc=exc,
            )
            return []

    def _resolve_kind(self, summary: MetadataObjectSummary) -> ObjectKind | None:
        try:
            return kind_from_plural(summary.object_type)
        except ValueError:
            self.report.objects_skipped_unknown_kind += 1
            self.report.report_warning(
                message="unknown 1C object kind, skipping",
                context=f"object_type={summary.object_type!r}, name={summary.name!r}",
            )
            return None

    def _fetch_detail(
        self,
        summary: MetadataObjectSummary,
    ) -> MetadataObjectDetail | None:
        """Безопасно прочитать ``/objects/{type}/{name}``.

        Возвращает ``None`` при любой ошибке: отсутствие detail-а не
        должно ронять ingestion объекта целиком — базовые аспекты всё
        равно эмитятся из summary.
        """
        try:
            return self._client.get_object_detail(summary.object_type, summary.name)
        except Exception as exc:
            self.report.report_warning(
                message="failed to fetch /objects/{type}/{name}, "
                "schema/kind-props/attributes will be skipped",
                context=f"object={summary.full_name!r}",
                exc=exc,
            )
            return None

    def _fetch_tabular_parts(
        self,
        kind: ObjectKind,
        summary: MetadataObjectSummary,
    ) -> list[TabularPart]:
        if not self.config.ingestion.tabular_sections:
            return []
        if not spec_for(kind).supports_tabular_sections:
            return []
        if not self.config.object_filters.should_fetch_tabular_sections(
            summary.object_type,
            summary.name,
        ):
            return []
        try:
            parts = self._client.get_tabular_parts(summary.object_type, summary.name)
        except Exception as exc:
            self.report.report_warning(
                message="failed to fetch /tabular-parts, container and TP datasets will be skipped",
                context=f"object={summary.full_name!r}",
                exc=exc,
            )
            return []
        return [
            part
            for part in parts
            if self.config.object_filters.includes_tabular_section(
                summary.object_type,
                summary.name,
                part.name,
            )
        ]

    def _emit_for_object(
        self,
        kind: ObjectKind,
        summary: MetadataObjectSummary,
        *,
        object_uuid: str,
        tabular_parts: tuple[TabularPart, ...],
        tabular_section_uuid_by_name: Mapping[str, str],
        relationships: DomainRelationshipsAccumulator,
        tabular_urn_by_object_key: dict[tuple[str, str, str], str],
    ) -> Iterable[MetadataWorkUnit]:
        """Эмитировать полный набор workunits для одного объекта 1С.

        Порядок шагов важен только для читаемости логов: DataHub GMS
        принимает аспекты в любом порядке, идемпотентно. Однако
        dataset-aspects идут раньше ``schemaMetadata``/relationships —
        так удобнее отлаживать при частичном прогоне.

        UUID объекта и включённых ТЧ уже проверены в
        ``_validate_scoped_objects()`` до первой эмиссии workunit-ов. Если
        ``ConfigDumpInfo.xml`` не соответствует базе 1С, ingestion падает
        до частичного обновления каталога.
        """
        overrides = self.config.transliteration.overrides
        env = self.config.env
        infobase_name = self.config.infobase.name
        infobase_urn = infobase_container_urn_for(
            infobase_name=infobase_name,
            env=env,
        )

        detail = self._fetch_detail(summary)
        has_tp = bool(tabular_parts)

        if kind not in self._emitted_type_folders:
            yield from build_type_folder_workunits(
                kind=kind,
                infobase_name=infobase_name,
                env=env,
            )
            self._emitted_type_folders.add(kind)
            self.report.type_folders_emitted += 1

        type_folder_urn = type_folder_container_urn_for(
            kind,
            infobase_name=infobase_name,
            env=env,
        )

        object_container_urn: str | None = None
        if has_tp:
            object_container_urn = build_container_urn(
                infobase_name=infobase_name,
                object_uuid=object_uuid,
                env=env,
            )
            yield from build_container_workunits(
                kind=kind,
                summary=summary,
                object_uuid=object_uuid,
                infobase_name=infobase_name,
                env=env,
                overrides=overrides,
                configuration_name=self.config.infobase.name,
            )
            self.report.containers_emitted += 1

        dataset_parent_urns: tuple[str, ...]
        if object_container_urn is not None:
            dataset_parent_urns = (infobase_urn, type_folder_urn, object_container_urn)
        else:
            dataset_parent_urns = (infobase_urn, type_folder_urn)
        parent_urn = dataset_urn(
            infobase_name=infobase_name,
            object_uuid=object_uuid,
            env=env,
        )
        parent_ds_name = _legacy_translit_dataset_name(
            kind,
            summary.name,
            overrides=overrides,
        )

        attributes_uuid_map: dict[str, str] = {}
        if detail is not None and self.config.ingestion.attributes:
            attributes_uuid_map = self._build_attributes_uuid_map(
                kind=kind,
                summary=summary,
                ts_name=None,
                attributes=detail.attributes,
                overrides=overrides,
            )

        yield from build_dataset_workunits(
            kind=kind,
            summary=summary,
            object_uuid=object_uuid,
            infobase_name=infobase_name,
            env=env,
            overrides=overrides,
            parent_container_urns=dataset_parent_urns,
            configuration_name=self.config.infobase.name,
            comment=detail.comment if detail is not None else None,
            attributes_uuid_map=attributes_uuid_map or None,
        )
        self.report.objects_emitted += 1

        # `attributes=False` в recipe глушит только прикладные реквизиты —
        # стандартные (Ref/Code/Date/...) эмитируются всегда, см. docstring
        # `IngestionOptionsConfig.attributes`. Для констант синтетическое
        # поле Value сохраняем всегда: без него scalar dataset стал бы пустым.
        if detail is not None:
            user_attributes = (
                detail.attributes
                if self.config.ingestion.attributes or kind is ObjectKind.CONSTANT
                else []
            )
            yield build_schema_metadata_workunit(
                dataset_urn=parent_urn,
                dataset_name=parent_ds_name,
                kind=kind,
                object_name=summary.name,
                user_attributes=user_attributes,
                overrides=overrides,
            )
            self.report.schema_metadata_emitted += 1

        if detail is not None:
            yield from self._emit_kind_properties(parent_urn, kind, detail)

        tp_urn_by_name: dict[str, str] = {}
        if has_tp and object_container_urn is not None:
            tp_urns: list[str] = []
            for tp in tabular_parts:
                ts_uuid = tabular_section_uuid_by_name[tp.name]
                emission = build_tabular_part_emission(
                    parent_kind=kind,
                    parent_summary=summary,
                    parent_object_uuid=object_uuid,
                    infobase_name=infobase_name,
                    tabular_part=tp,
                    tabular_section_uuid=ts_uuid,
                    parent_dataset_urn=parent_urn,
                    parent_container_urns=(
                        infobase_urn,
                        type_folder_urn,
                        object_container_urn,
                    ),
                    env=env,
                    overrides=overrides,
                    configuration_name=self.config.infobase.name,
                    include_relationships=False,
                )
                yield from emission.workunits
                tp_urns.append(emission.tabular_section_urn)
                tp_urn_by_name[tp.name] = emission.tabular_section_urn
                tabular_urn_by_object_key[(summary.object_type, summary.name, tp.name)] = (
                    emission.tabular_section_urn
                )
                relationships.add(
                    entity_urn=emission.tabular_section_urn,
                    relationship=REL_IS_TABULAR_PART_OF,
                    target_urn=parent_urn,
                )
                self.report.tabular_parts_emitted += 1

            if tp_urns:
                relationships.add_many(
                    entity_urn=parent_urn,
                    relationship=REL_HAS_TABULAR_PART,
                    target_urns=tp_urns,
                )

        # DB-mapping эмитится после родителя и ТЧ: нужны их URN.
        # Константы пропускаем, потому что их общая физическая таблица
        # не является 1:1 sibling-представлением отдельной Constant.*.
        if self.config.ingestion.db_mapping and kind is not ObjectKind.CONSTANT:
            yield from self._emit_db_mapping(
                summary=summary,
                onec_parent_urn=parent_urn,
                tp_urn_by_name=tp_urn_by_name,
                relationships=relationships,
            )

    def _fetch_db_mapping(
        self,
        summary: MetadataObjectSummary,
    ) -> DbMapping | None:
        """Безопасно прочитать ``/db-mapping/{type}/{name}``.

        Отсутствие маппинга — не ошибка: это нормально для объектов без
        физического представления в PG (например, редкий ``Перечисление``).
        Возвращаем ``None``, инкрементим счётчик и идём дальше.
        """
        try:
            return self._client.get_db_mapping(summary.object_type, summary.name)
        except Exception as exc:
            self.report.db_mapping_not_found += 1
            self.report.report_warning(
                message="failed to fetch /db-mapping, DB mapping will be skipped",
                context=f"object={summary.full_name!r}",
                exc=exc,
            )
            return None

    def _fetch_lineage(
        self,
        object_full_names: list[str],
        *,
        object_keys: set[tuple[str, str]],
        kinds: tuple[str, ...],
    ) -> list[LineageEdge]:
        """Прочитать ``/lineage`` для объектов текущего ingestion.

        Lineage считается authoritative частью 1С ingestion. Ошибки
        endpoint-а не превращаются в warning, иначе некорректное manual lineage
        правило могло бы дать "успешный" ingest без актуального lineage-графа.
        """
        if not kinds:
            return []
        if self._lineage_filter_query_is_too_long(object_full_names, kinds):
            return self._fetch_lineage_without_object_filter(
                object_keys=object_keys,
                kinds=kinds,
            )
        try:
            return self._client.get_lineage(
                objects=object_full_names,
                kinds=list(kinds),
            )
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 414:
                return self._fetch_lineage_without_object_filter(
                    object_keys=object_keys,
                    kinds=kinds,
                )
            raise

    def _lineage_filter_query_is_too_long(
        self,
        object_full_names: list[str],
        kinds: tuple[str, ...],
    ) -> bool:
        """Проверить, не станет ли GET `/lineage` длиннее типичных HTTP-лимитов."""
        params = {
            "objects": ",".join(object_full_names),
            "kinds": ",".join(kinds),
        }
        return len(urlencode(params)) > LINEAGE_FILTER_QUERY_CHAR_LIMIT

    def _fetch_lineage_without_object_filter(
        self,
        *,
        object_keys: set[tuple[str, str]],
        kinds: tuple[str, ...],
    ) -> list[LineageEdge]:
        """Обойти лимит длины URL и сохранить фильтрацию по текущему scope.

        1С API фильтрует `/lineage?objects=...` так, что и upstream, и
        downstream должны входить в список. Для большого scope query string
        может превысить лимит веб-сервера. Поэтому запрашиваем lineage только
        по видам связей, а затем применяем тот же scope-фильтр локально.
        """
        logger.info(
            "1C lineage object filter is too large; fetching lineage by kinds "
            "and filtering locally for %s objects",
            len(object_keys),
        )
        result: list[LineageEdge] = []
        for edge in self._client.get_lineage(objects=None, kinds=list(kinds)):
            upstream_key = (edge.upstream_object_type, edge.upstream_name)
            downstream_key = (edge.downstream_object_type, edge.downstream_name)
            if upstream_key in object_keys and downstream_key in object_keys:
                result.append(edge)
        return result

    def _fetch_current_upstream_lineage(
        self,
        downstream_urns: Iterable[str],
    ) -> dict[str, UpstreamLineageClass | None]:
        """Прочитать текущий ``upstreamLineage`` перед patch-обновлением.

        Direct lineage обновляется не полным aspect-ом, а точечным patch-ем:
        старые 1С-owned edges удаляются, ручные и внешние edges остаются. Для
        такого merge нужен текущий aspect из GMS primary store.
        """
        graph = self.ctx.require_graph("1C direct lineage merge")
        urns = sorted(dict.fromkeys(downstream_urns))
        entities = graph.get_entities(
            "dataset",
            urns,
            aspects=[UpstreamLineageClass.ASPECT_NAME],
        )
        current: dict[str, UpstreamLineageClass | None] = {urn: None for urn in urns}
        for urn, aspects in entities.items():
            aspect_with_system_metadata = aspects.get(UpstreamLineageClass.ASPECT_NAME)
            if aspect_with_system_metadata is None:
                continue
            current[urn] = aspect_with_system_metadata[0]
        return current

    def _fetch_references(self, object_full_names: list[str]) -> list[Reference]:
        """Безопасно прочитать ``/references`` для объектов текущего ingestion."""
        try:
            return self._client.get_references(
                objects=object_full_names,
                level="tables",
            )
        except Exception as exc:
            self.report.report_warning(
                message="failed to fetch /references, domain references will be skipped",
                context=f"objects_count={len(object_full_names)}",
                exc=exc,
            )
            return []

    def _fetch_integration_services(self) -> list[IntegrationService]:
        """Прочитать ``/integration-services`` по opt-in scope recipe."""
        scope = self.config.integration_services
        try:
            services = self._client.get_integration_services(
                types=scope.include_types or None,
                services=scope.service_full_names() or None,
                endpoints=scope.endpoint_full_names() or None,
            )
        except Exception as exc:
            self.report.report_failure(
                message="failed to fetch /integration-services",
                context=(
                    f"types={scope.include_types!r}, "
                    f"services={scope.service_full_names()!r}, "
                    f"endpoints={scope.endpoint_full_names()!r}"
                ),
                exc=exc,
            )
            raise
        self._validate_integration_services_response(services)
        return services

    def _validate_integration_services_response(
        self,
        services: list[IntegrationService],
    ) -> None:
        """Fail-fast если explicit recipe scope не найден в ответе 1С API."""
        scope = self.config.integration_services

        expected_services = set(scope.service_full_names())
        if expected_services:
            actual_services = {
                service.full_name
                for service in services
                if scope.includes_service(service.service_type, service.name)
            }
            missing_services = sorted(expected_services - actual_services)
            if missing_services:
                message = "explicit integration services were not returned by /integration-services"
                context = f"missing_services={missing_services!r}"
                self.report.report_failure(message=message, context=context)
                raise ValueError(f"{message}: {context}")

        expected_endpoints = set(scope.endpoint_full_names())
        if expected_endpoints:
            actual_endpoints = {
                endpoint.full_name
                for service in services
                for endpoint in service.endpoints
                if scope.includes_service(service.service_type, service.name)
            }
            missing_endpoints = sorted(expected_endpoints - actual_endpoints)
            if missing_endpoints:
                message = (
                    "explicit integration service endpoints were not returned "
                    "by /integration-services"
                )
                context = f"missing_endpoints={missing_endpoints!r}"
                self.report.report_failure(message=message, context=context)
                raise ValueError(f"{message}: {context}")

    def _emit_integration_services(
        self,
        *,
        scoped_services: Iterable[_ScopedIntegrationService],
        object_urn_by_full_name: Mapping[str, str],
    ) -> Iterable[MetadataWorkUnit]:
        """Эмитировать HTTP/Web-сервисы как DataFlow/DataJob metadata-only.

        В этом блоке намеренно нет ``DataJobInputOutput``: 1С metadata API не
        знает внешних outputs, а частичный aspect может стереть связи,
        созданные отдельным integration lineage source.
        """
        for scoped in scoped_services:
            service = scoped.service

            if service.service_type not in self._emitted_integration_service_type_folders:
                yield from build_integration_service_type_folder_workunits(
                    service_type=service.service_type,
                    infobase_name=self.config.infobase.name,
                    env=self.config.env,
                )
                self._emitted_integration_service_type_folders.add(service.service_type)
                self.report.integration_service_type_folders_emitted += 1

            emission = build_integration_service_workunits(
                service=service,
                service_uuid=scoped.service_uuid,
                endpoint_uuid_by_full_name=scoped.endpoint_uuid_by_full_name,
                object_urn_by_full_name=object_urn_by_full_name,
                infobase_name=self.config.infobase.name,
                env=self.config.env,
            )
            yield from emission.workunits
            self.report.integration_services_emitted += 1
            self.report.integration_endpoints_emitted += emission.endpoints_emitted
            self.report.integration_internal_inputs_resolved += emission.internal_inputs_resolved
            self.report.integration_internal_inputs_unresolved += (
                emission.internal_inputs_unresolved
            )

    def _collect_reference_relationships(
        self,
        *,
        object_full_names: list[str],
        urn_by_object_key: Mapping[tuple[str, str], str],
        tabular_urn_by_object_key: Mapping[tuple[str, str, str], str],
        relationships: DomainRelationshipsAccumulator,
    ) -> None:
        """``/references`` отдаёт структурные доменные ссылки между объектами 1С.
        Source превращает их в custom relationships, но не в DataHub lineage.
        """
        refs = self._fetch_references(object_full_names)
        self.report.reference_edges_fetched = len(refs)
        if not refs:
            return

        for ref in refs:
            source_urn = self._resolve_reference_source_urn(
                ref=ref,
                urn_by_object_key=urn_by_object_key,
                tabular_urn_by_object_key=tabular_urn_by_object_key,
            )
            if source_urn is None:
                self.report.reference_edges_skipped += 1
                self.report.reference_edges_skipped_missing_source += 1
                continue

            target_urn = urn_by_object_key.get(
                (
                    ref.target_object_type,
                    ref.target_name,
                )
            )
            if target_urn is None:
                self.report.reference_edges_skipped += 1
                self.report.reference_edges_skipped_missing_target += 1
                self.report.report_warning(
                    message="reference target object was not emitted, skipping",
                    context=(
                        f"source={ref.source_object_type}.{ref.source_name!s}, "
                        f"source_tabular_part={ref.source_tabular_part!r}, "
                        f"target={ref.target_object_type}.{ref.target_name}"
                    ),
                )
                continue

            relationships.add(
                entity_urn=source_urn,
                relationship=REL_REFERS_TO_OBJECT,
                target_urn=target_urn,
            )
            relationships.add(
                entity_urn=target_urn,
                relationship=REL_IS_REFERENCED_BY_OBJECT,
                target_urn=source_urn,
            )
            self.report.reference_edges_emitted += 1

    def _resolve_reference_source_urn(
        self,
        *,
        ref: Reference,
        urn_by_object_key: Mapping[tuple[str, str], str],
        tabular_urn_by_object_key: Mapping[tuple[str, str, str], str],
    ) -> str | None:
        """Найти source URN для reference: ТЧ при наличии, иначе родитель."""
        if ref.source_tabular_part:
            key = (ref.source_object_type, ref.source_name, ref.source_tabular_part)
            urn = tabular_urn_by_object_key.get(key)
            if urn is None:
                self.report.report_warning(
                    message="reference source tabular part was not emitted, skipping",
                    context=(
                        f"source={ref.source_object_type}.{ref.source_name}, "
                        f"source_tabular_part={ref.source_tabular_part!r}, "
                        f"target={ref.target_object_type}.{ref.target_name}"
                    ),
                )
            return urn

        urn = urn_by_object_key.get((ref.source_object_type, ref.source_name))
        if urn is None:
            self.report.report_warning(
                message="reference source object was not emitted, skipping",
                context=(
                    f"source={ref.source_object_type}.{ref.source_name}, "
                    f"target={ref.target_object_type}.{ref.target_name}"
                ),
            )
        return urn

    def _emit_lineage(
        self,
        *,
        object_full_names: list[str],
        urn_by_object_key: Mapping[tuple[str, str], str],
        object_uuid_by_object_key: Mapping[tuple[str, str], str],
        object_full_name_by_key: Mapping[tuple[str, str], str],
        tabular_urn_by_object_key: Mapping[tuple[str, str, str], str],
    ) -> Iterable[MetadataWorkUnit]:
        """Эмитировать lineage между 1С-датасетами и процессами."""
        enabled_kinds = self.config.ingestion.effective_lineage_kinds
        enabled_kind_set = set(enabled_kinds)
        direct_kind_set = set(DIRECT_UPSTREAM_LINEAGE_KINDS) & enabled_kind_set
        process_lineage_enabled = REGISTER_MOVEMENT_LINEAGE_KIND in enabled_kind_set
        scoped_document_keys = {
            key for key in object_uuid_by_object_key if key[0] == DOCUMENT_OBJECT_TYPE_PLURAL
        }

        edges = self._fetch_lineage(
            object_full_names,
            object_keys=set(urn_by_object_key),
            kinds=enabled_kinds,
        )
        self.report.lineage_edges_fetched = len(edges)

        direct_upstream_edges: list[LineageEdge] = []
        register_movement_edges: list[LineageEdge] = []
        for edge in edges:
            if edge.kind not in enabled_kind_set:
                self.report.lineage_edges_skipped_unsupported_kind += 1
                continue
            if edge.kind in direct_kind_set:
                direct_upstream_edges.append(edge)
            elif edge.kind == REGISTER_MOVEMENT_LINEAGE_KIND and process_lineage_enabled:
                register_movement_edges.append(edge)

        direct_upstream_emission = build_upstream_lineage_workunits(
            edges=direct_upstream_edges,
            urn_by_object_key=urn_by_object_key,
            authoritative_downstream_urns=urn_by_object_key.values(),
            current_upstream_lineage_by_downstream_urn=(
                self._fetch_current_upstream_lineage(urn_by_object_key.values())
            ),
        )
        self.report.lineage_edges_emitted += direct_upstream_emission.edges_emitted
        self.report.lineage_edges_skipped += direct_upstream_emission.edges_skipped
        self.report.lineage_owned_edges_removed += direct_upstream_emission.owned_edges_removed
        self.report.lineage_external_edges_preserved += (
            direct_upstream_emission.external_edges_preserved
        )
        yield from direct_upstream_emission.workunits

        if process_lineage_enabled:
            posting_emission = build_posting_process_lineage_workunits(
                edges=register_movement_edges,
                urn_by_object_key=urn_by_object_key,
                object_uuid_by_object_key=object_uuid_by_object_key,
                object_full_name_by_key=object_full_name_by_key,
                tabular_urn_by_object_key=tabular_urn_by_object_key,
                infobase_name=self.config.infobase.name,
                env=self.config.env,
            )
            self.report.lineage_edges_emitted += posting_emission.output_edges_emitted
            self.report.lineage_edges_skipped += posting_emission.edges_skipped
            self.report.lineage_processes_emitted += posting_emission.processes_emitted
            self.report.lineage_process_input_edges_emitted += posting_emission.input_edges_emitted
            self.report.lineage_process_output_edges_emitted += (
                posting_emission.output_edges_emitted
            )
            yield from posting_emission.workunits
            stale_document_keys = scoped_document_keys - posting_emission.document_keys_emitted
            if stale_document_keys:
                removal_emission = build_removed_posting_process_workunits(
                    object_uuid_by_object_key=object_uuid_by_object_key,
                    document_keys=stale_document_keys,
                    infobase_name=self.config.infobase.name,
                    env=self.config.env,
                )
                self.report.lineage_processes_removed += removal_emission.processes_removed
                yield from removal_emission.workunits
        else:
            removal_emission = build_removed_posting_process_workunits(
                object_uuid_by_object_key=object_uuid_by_object_key,
                document_keys=scoped_document_keys,
                infobase_name=self.config.infobase.name,
                env=self.config.env,
            )
            self.report.lineage_processes_removed += removal_emission.processes_removed
            yield from removal_emission.workunits

    def _emit_db_mapping(
        self,
        *,
        summary: MetadataObjectSummary,
        onec_parent_urn: str,
        tp_urn_by_name: Mapping[str, str],
        relationships: DomainRelationshipsAccumulator,
    ) -> Iterable[MetadataWorkUnit]:
        """Эмитировать PG-слой для объекта.

        PG-датасет создаётся для каждой известной таблицы из ``/db-mapping``.
        Связка с 1С-датасетом добавляется только для ``Main`` и
        ``TabularSection``; таблицы итогов регистров остаются отдельным
        физическим слоем.
        """
        mapping = self._fetch_db_mapping(summary)
        if mapping is None or not mapping.tables:
            return

        pg_cfg = self.config.postgres
        database = self.config.pg_database()
        schema = pg_cfg.schema_name
        pg_env = self.config.pg_env()
        overrides = self.config.transliteration.overrides

        for table in mapping.tables:
            if table.purpose not in _KNOWN_TABLE_PURPOSES:
                self.report.db_mapping_unknown_purpose_skipped += 1
                self.report.report_warning(
                    message="db-mapping table has unknown purpose, skipping",
                    context=(
                        f"object={summary.full_name!r}, "
                        f"db_table={table.db_table_name!r}, "
                        f"purpose={table.purpose!r}"
                    ),
                )
                continue

            if self._db_mapping_table_excluded_by_object_filters(
                summary=summary,
                table=table,
            ):
                continue

            emission = build_pg_dataset_workunits(
                database=database,
                schema=schema,
                table=table,
                env=pg_env,
            )
            yield from emission.workunits
            self.report.pg_datasets_emitted += 1

            onec_urn = self._resolve_onec_urn_for_table(
                table=table,
                onec_parent_urn=onec_parent_urn,
                tp_urn_by_name=tp_urn_by_name,
                summary=summary,
            )
            if onec_urn is None:
                # Либо purpose=Totals/* (нет 1С-двойника), либо
                # TabularSection без резолва (warning уже залогирован).
                # В любом случае: только PG-датасет, без Sibling.
                self.report.pg_aux_datasets_emitted += 1
                continue

            if self.config.ingestion.emit_db_siblings:
                yield from build_siblings_workunits(
                    onec_urn=onec_urn,
                    pg_urn=emission.pg_urn,
                )
            # Кастомные аспекты (oneCDbMapping + mapsToDbTable) попадут под
            # фильтр emit_custom_aspects в `get_workunits_internal` —
            # отдельной проверки здесь не нужно.
            db_mapping_wu = build_db_mapping_aspect_wu(
                onec_urn=onec_urn,
                table=table,
                translit_overrides=overrides,
            )
            if db_mapping_wu is not None:
                yield db_mapping_wu
            relationships.add(
                entity_urn=onec_urn,
                relationship=REL_MAPS_TO_DB_TABLE,
                target_urn=emission.pg_urn,
            )
            self.report.db_mappings_emitted += 1

    def _db_mapping_table_excluded_by_object_filters(
        self,
        *,
        summary: MetadataObjectSummary,
        table: DbTableMapping,
    ) -> bool:
        """True если DB-таблица соответствует ТЧ, исключённой recipe-фильтрами."""
        return (
            table.purpose == TABLE_PURPOSE_TABULAR_SECTION
            and table.tabular_section_name is not None
            and not self.config.object_filters.includes_tabular_section(
                summary.object_type,
                summary.name,
                table.tabular_section_name,
            )
        )

    def _resolve_onec_urn_for_table(
        self,
        *,
        table: DbTableMapping,
        onec_parent_urn: str,
        tp_urn_by_name: Mapping[str, str],
        summary: MetadataObjectSummary,
    ) -> str | None:
        """Определить, к какому 1С-датасету привязана таблица СУБД.

        ``None`` означает, что PG-датасет остаётся без Sibling-обвязки.
        """
        if not is_siblable_purpose(table.purpose):
            return None
        if table.purpose == TABLE_PURPOSE_MAIN:
            return onec_parent_urn
        # purpose == TabularSection
        if not table.tabular_section_name:
            self.report.report_warning(
                message="db-mapping TabularSection without tabular_section_name, "
                "skipping Sibling for this table",
                context=(f"object={summary.full_name!r}, db_table={table.db_table_name!r}"),
            )
            return None
        urn = tp_urn_by_name.get(table.tabular_section_name)
        if urn is None:
            self.report.report_warning(
                message="db-mapping references unknown tabular section, "
                "skipping Sibling for this table",
                context=(
                    f"object={summary.full_name!r}, "
                    f"tabular_section={table.tabular_section_name!r}, "
                    f"db_table={table.db_table_name!r}, "
                    f"known={sorted(tp_urn_by_name)!r}"
                ),
            )
            return None
        return urn

    def _build_attributes_uuid_map(
        self,
        *,
        kind: ObjectKind,
        summary: MetadataObjectSummary,
        ts_name: str | None,
        attributes: Iterable[Any],
        overrides: Mapping[str, str] | None,
    ) -> dict[str, str]:
        """Стандартные реквизиты пропускаются: их ``fieldPath`` берётся из
        локального справочника, а не из API.
        """
        result: dict[str, str] = {}
        for attr in attributes:
            if getattr(attr, "role", "attribute") == "standard":
                continue
            attr_name = attr.name
            if kind is ObjectKind.CONSTANT and attr_name == "Value":
                # Value — синтетическое поле скалярной константы. В
                # ConfigDumpInfo.xml у константы есть UUID самого объекта,
                # но нет отдельного Attribute.Value.
                continue
            attr_uuid = self._uuid_index.attribute_uuid(
                kind,
                summary.name,
                ts_name,
                attr_name,
            )
            if attr_uuid is None:
                self.report.attributes_missing_uuid += 1
                self.report.report_warning(
                    message="attribute UUID not found in ConfigDumpInfo.xml, "
                    "attributesUuidMap entry skipped",
                    context=(
                        f"object={summary.full_name!r}, "
                        f"tabular_section={ts_name!r}, "
                        f"attribute={attr_name!r}"
                    ),
                )
                continue
            try:
                field_path = transliterate(attr_name, overrides=overrides)
            except Exception as exc:
                # Транслит не должен ронять ingestion: worst case —
                # запись не попадёт в attributesUuidMap, но
                # schemaMetadata всё равно эмитится.
                self.report.report_warning(
                    message="failed to transliterate attribute name, "
                    "attributesUuidMap entry skipped",
                    context=(f"object={summary.full_name!r}, attribute={attr_name!r}"),
                    exc=exc,
                )
                continue
            result[field_path] = attr_uuid
        return result

    def _emit_kind_properties(
        self,
        parent_urn: str,
        kind: ObjectKind,
        detail: MetadataObjectDetail,
    ) -> Iterable[MetadataWorkUnit]:
        wu: MetadataWorkUnit | None = None
        properties_family = spec_for(kind).properties_family
        if properties_family == "catalog":
            wu = build_catalog_properties_workunit(
                entity_urn=parent_urn,
                properties=detail.catalog_properties,
            )
        elif properties_family == "document":
            wu = build_document_properties_workunit(
                entity_urn=parent_urn,
                properties=detail.document_properties,
            )
        elif properties_family == "register":
            wu = build_register_properties_workunit(
                entity_urn=parent_urn,
                properties=detail.register_properties,
                register_kind=register_kind_value_for(kind),
            )
        if wu is not None:
            yield wu
            self.report.kind_properties_emitted += 1
