"""Эмиссия HTTP/Web-сервисов 1С как DataFlow/DataJob.

HTTP/Web-сервисы 1С являются integration interface, а не data assets. Поэтому
они не попадают в ``object_filters`` и не эмитятся как ``Dataset``. Модель:

* ``DataFlow`` — сервис (`HTTPService.X` / `WebService.Y`);
* ``DataJob`` — executable endpoint: HTTP method URL-шаблона или WebService
  operation;
* ``DataJobInputOutput`` здесь намеренно не эмитится. 1С metadata source не
  знает внешних потребителей/outputs, а частичный aspect может стереть связи,
  записанные отдельным integration lineage source.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from datahub.emitter.mce_builder import (
    make_container_urn,
    make_data_flow_urn,
    make_data_job_urn_with_flow,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    BrowsePathEntryClass,
    BrowsePathsV2Class,
    ContainerClass,
    ContainerPropertiesClass,
    DataFlowInfoClass,
    DataJobInfoClass,
    StatusClass,
    SubTypesClass,
)

from datahub_1c.api.models import IntegrationEndpoint, IntegrationService
from datahub_1c.config import (
    INTEGRATION_SERVICE_TYPE_HTTP,
    INTEGRATION_SERVICE_TYPE_WEB,
)
from datahub_1c.mapping.browse_paths import build_browse_paths_v2_workunit
from datahub_1c.mapping.urn import (
    PLATFORM_1C,
    infobase_container_urn_for,
    validate_infobase_name,
)

INTEGRATION_SERVICE_TYPE_FOLDER_SUB_TYPE: str = "1C Integration Service Kind Folder"
HTTP_SERVICE_PROCESS_KIND: str = "http_service"
WEB_SERVICE_PROCESS_KIND: str = "web_service"
HTTP_METHOD_PROCESS_KIND: str = "http_service_method"
WEB_OPERATION_PROCESS_KIND: str = "web_service_operation"


@dataclass(frozen=True)
class IntegrationServiceEmission:
    """Результат эмиссии одного service flow и его jobs."""

    workunits: tuple[MetadataWorkUnit, ...]
    endpoints_emitted: int
    internal_inputs_resolved: int
    internal_inputs_unresolved: int


def integration_service_type_folder_key(
    service_type: str,
    *,
    infobase_name: str,
    env: str,
) -> str:
    """Стабильный ключ контейнера-папки ``HTTPServices``/``WebServices``."""
    infobase = validate_infobase_name(infobase_name)
    if not env:
        raise ValueError("empty env for integration service folder")
    return f"{infobase}:{service_type}:{env}"


def integration_service_type_folder_urn_for(
    service_type: str,
    *,
    infobase_name: str,
    env: str,
) -> str:
    return make_container_urn(
        integration_service_type_folder_key(
            service_type,
            infobase_name=infobase_name,
            env=env,
        )
    )


def build_integration_service_type_folder_workunits(
    *,
    service_type: str,
    infobase_name: str,
    env: str,
) -> Iterable[MetadataWorkUnit]:
    """Контейнер-папка для сервисов одного вида в Browse/Navigate."""
    urn = integration_service_type_folder_urn_for(
        service_type,
        infobase_name=infobase_name,
        env=env,
    )
    infobase_urn = infobase_container_urn_for(infobase_name=infobase_name, env=env)

    yield MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=ContainerPropertiesClass(
            name=service_type,
            qualifiedName=service_type,
            customProperties={"serviceType": service_type},
        ),
    ).as_workunit()
    yield MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=SubTypesClass(typeNames=[INTEGRATION_SERVICE_TYPE_FOLDER_SUB_TYPE]),
    ).as_workunit()
    yield MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=ContainerClass(container=infobase_urn),
    ).as_workunit()
    yield build_browse_paths_v2_workunit(entity_urn=urn, parent_urns=(infobase_urn,))


def build_integration_service_workunits(
    *,
    service: IntegrationService,
    service_uuid: str,
    endpoint_uuid_by_full_name: Mapping[str, str],
    object_urn_by_full_name: Mapping[str, str],
    infobase_name: str,
    env: str,
) -> IntegrationServiceEmission:
    """Построить ``DataFlow`` сервиса и ``DataJob`` его endpoint-ов."""
    infobase = validate_infobase_name(infobase_name)
    flow_urn = integration_service_flow_urn(
        service_type=service.service_type,
        service_uuid=service_uuid,
        infobase_name=infobase,
        env=env,
    )
    folder_urn = integration_service_type_folder_urn_for(
        service.service_type,
        infobase_name=infobase,
        env=env,
    )
    infobase_urn = infobase_container_urn_for(infobase_name=infobase, env=env)
    flow_name = _service_display_name(service)
    process_kind = _service_process_kind(service.service_type)

    workunits: list[MetadataWorkUnit] = [
        MetadataChangeProposalWrapper(
            entityUrn=flow_urn,
            aspect=DataFlowInfoClass(
                name=flow_name,
                description=service.comment or service.synonym,
                customProperties=_service_custom_properties(
                    service=service,
                    service_uuid=service_uuid,
                    process_kind=process_kind,
                    infobase_name=infobase,
                ),
                env=env,
            ),
        ).as_workunit(),
        MetadataChangeProposalWrapper(
            entityUrn=flow_urn,
            aspect=StatusClass(removed=False),
        ).as_workunit(),
        MetadataChangeProposalWrapper(
            entityUrn=flow_urn,
            aspect=BrowsePathsV2Class(
                path=[
                    _browse_entry(infobase_urn),
                    _browse_entry(folder_urn),
                ]
            ),
        ).as_workunit(),
    ]

    endpoints_emitted = 0
    internal_inputs_resolved = 0
    internal_inputs_unresolved = 0

    for endpoint in service.endpoints:
        endpoint_uuid = endpoint_uuid_by_full_name.get(endpoint.full_name)
        if endpoint_uuid is None:
            continue
        job_urn = integration_endpoint_job_urn(
            flow_urn=flow_urn,
            endpoint_uuid=endpoint_uuid,
            endpoint_type=endpoint.endpoint_type,
        )
        endpoint_props, resolved, unresolved = _endpoint_custom_properties(
            service=service,
            endpoint=endpoint,
            endpoint_uuid=endpoint_uuid,
            infobase_name=infobase,
            object_urn_by_full_name=object_urn_by_full_name,
        )
        internal_inputs_resolved += resolved
        internal_inputs_unresolved += unresolved
        workunits.extend(
            [
                MetadataChangeProposalWrapper(
                    entityUrn=job_urn,
                    aspect=DataJobInfoClass(
                        name=_endpoint_display_name(service, endpoint),
                        type=_endpoint_job_type(endpoint),
                        description=endpoint.comment or endpoint.synonym,
                        flowUrn=flow_urn,
                        customProperties=endpoint_props,
                        env=env,
                    ),
                ).as_workunit(),
                MetadataChangeProposalWrapper(
                    entityUrn=job_urn,
                    aspect=StatusClass(removed=False),
                ).as_workunit(),
                MetadataChangeProposalWrapper(
                    entityUrn=job_urn,
                    aspect=BrowsePathsV2Class(
                        path=[
                            _browse_entry(infobase_urn),
                            _browse_entry(folder_urn),
                            _browse_entry(flow_urn),
                        ]
                    ),
                ).as_workunit(),
            ]
        )
        endpoints_emitted += 1

    return IntegrationServiceEmission(
        workunits=tuple(workunits),
        endpoints_emitted=endpoints_emitted,
        internal_inputs_resolved=internal_inputs_resolved,
        internal_inputs_unresolved=internal_inputs_unresolved,
    )


def integration_service_flow_urn(
    *,
    service_type: str,
    service_uuid: str,
    infobase_name: str,
    env: str,
) -> str:
    flow_id = (
        f"{validate_infobase_name(infobase_name)}.integration."
        f"{_service_urn_type_token(service_type)}.{service_uuid}"
    )
    return make_data_flow_urn(
        orchestrator=PLATFORM_1C,
        flow_id=flow_id,
        cluster=env,
    )


def integration_endpoint_job_urn(
    *,
    flow_urn: str,
    endpoint_uuid: str,
    endpoint_type: str,
) -> str:
    return make_data_job_urn_with_flow(
        flow_urn,
        f"{_endpoint_job_id_prefix(endpoint_type)}.{endpoint_uuid}",
    )


def _service_urn_type_token(service_type: str) -> str:
    if service_type == INTEGRATION_SERVICE_TYPE_HTTP:
        return "http"
    if service_type == INTEGRATION_SERVICE_TYPE_WEB:
        return "web"
    return service_type.lower()


def _endpoint_job_id_prefix(endpoint_type: str) -> str:
    if endpoint_type == "http_method":
        return "method"
    if endpoint_type == "web_operation":
        return "operation"
    return "endpoint"


def _service_display_name(service: IntegrationService) -> str:
    if service.service_type == INTEGRATION_SERVICE_TYPE_HTTP:
        return f"HTTP-сервис {service.name}"
    if service.service_type == INTEGRATION_SERVICE_TYPE_WEB:
        return f"Web-сервис {service.name}"
    return service.full_name


def _service_process_kind(service_type: str) -> str:
    if service_type == INTEGRATION_SERVICE_TYPE_HTTP:
        return HTTP_SERVICE_PROCESS_KIND
    if service_type == INTEGRATION_SERVICE_TYPE_WEB:
        return WEB_SERVICE_PROCESS_KIND
    return "integration_service"


def _service_custom_properties(
    *,
    service: IntegrationService,
    service_uuid: str,
    process_kind: str,
    infobase_name: str,
) -> dict[str, str]:
    props = {
        "processKind": process_kind,
        "infobaseName": infobase_name,
        "serviceType": service.service_type,
        "serviceName": service.name,
        "serviceFullName": service.full_name,
        "metadataUuid": service_uuid,
    }
    _add_optional(props, "synonym", service.synonym)
    _add_optional(props, "rootUrl", service.root_url)
    _add_optional(props, "reuseSessions", service.reuse_sessions)
    _add_optional(props, "sessionMaxAge", service.session_max_age)
    _add_optional(props, "namespace", service.namespace)
    _add_optional(props, "descriptorFileName", service.descriptor_file_name)
    return props


def _endpoint_display_name(
    service: IntegrationService,
    endpoint: IntegrationEndpoint,
) -> str:
    if endpoint.endpoint_type == "http_method":
        method = endpoint.http_method or endpoint.method_name or endpoint.name
        path = _join_http_path(service.root_url, endpoint.url_template)
        return f"{method} {path}" if path else str(method)
    if endpoint.endpoint_type == "web_operation":
        return f"Operation {endpoint.operation_name or endpoint.name}"
    return endpoint.name


def _join_http_path(root_url: str | None, template: str | None) -> str | None:
    parts = [part.strip("/") for part in (root_url, template) if part]
    if not parts:
        return None
    return "/" + "/".join(parts)


def _endpoint_job_type(endpoint: IntegrationEndpoint) -> str:
    if endpoint.endpoint_type == "http_method":
        return "1C_HTTP_SERVICE_METHOD"
    if endpoint.endpoint_type == "web_operation":
        return "1C_WEB_SERVICE_OPERATION"
    return "1C_INTEGRATION_ENDPOINT"


def _endpoint_process_kind(endpoint: IntegrationEndpoint) -> str:
    if endpoint.endpoint_type == "http_method":
        return HTTP_METHOD_PROCESS_KIND
    if endpoint.endpoint_type == "web_operation":
        return WEB_OPERATION_PROCESS_KIND
    return "integration_endpoint"


def _endpoint_custom_properties(
    *,
    service: IntegrationService,
    endpoint: IntegrationEndpoint,
    endpoint_uuid: str,
    infobase_name: str,
    object_urn_by_full_name: Mapping[str, str],
) -> tuple[dict[str, str], int, int]:
    props = {
        "processKind": _endpoint_process_kind(endpoint),
        "infobaseName": infobase_name,
        "serviceType": service.service_type,
        "serviceName": service.name,
        "serviceFullName": service.full_name,
        "endpointType": endpoint.endpoint_type,
        "endpointName": endpoint.name,
        "endpointFullName": endpoint.full_name,
        "metadataUuid": endpoint_uuid,
    }
    _add_optional(props, "synonym", endpoint.synonym)
    _add_optional(props, "urlTemplateName", endpoint.url_template_name)
    _add_optional(props, "urlTemplateFullName", endpoint.url_template_full_name)
    _add_optional(props, "urlTemplate", endpoint.url_template)
    _add_optional(props, "methodName", endpoint.method_name)
    _add_optional(props, "httpMethod", endpoint.http_method)
    _add_optional(props, "handler", endpoint.handler)
    _add_optional(props, "operationName", endpoint.operation_name)
    _add_optional(props, "procedureName", endpoint.procedure_name)
    _add_optional(props, "transactioned", endpoint.transactioned)
    _add_optional(props, "nillable", endpoint.nillable)
    _add_optional(props, "dataLockControlMode", endpoint.data_lock_control_mode)
    _add_optional(props, "returnXdtoType", endpoint.return_xdto_type)

    if endpoint.parameters:
        props["webServiceParameterNames"] = _json_array(
            parameter.name for parameter in endpoint.parameters
        )

    full_names: list[str] = []
    resolved_urns: list[str] = []
    unresolved: list[str] = []
    sources: list[str] = []
    confidences: list[str] = []
    for input_object in endpoint.input_objects:
        full_names.append(input_object.full_name)
        sources.append(input_object.source)
        confidences.append(input_object.confidence)
        urn = object_urn_by_full_name.get(input_object.full_name)
        if urn is None:
            unresolved.append(input_object.full_name)
        else:
            resolved_urns.append(urn)

    if full_names:
        props["internalInputObjectFullNames"] = _json_array(full_names)
        props["internalInputSources"] = _json_array(_dedupe(sources))
        props["internalInputConfidences"] = _json_array(_dedupe(confidences))
    if resolved_urns:
        props["internalInputDatasetUrns"] = _json_array(resolved_urns)
    if unresolved:
        props["internalInputUnresolvedFullNames"] = _json_array(unresolved)

    return props, len(resolved_urns), len(unresolved)


def _add_optional(props: dict[str, str], key: str, value: object | None) -> None:
    if value is None:
        return
    props[key] = str(value)


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _json_array(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def _browse_entry(urn: str) -> BrowsePathEntryClass:
    return BrowsePathEntryClass(id=urn, urn=urn)
