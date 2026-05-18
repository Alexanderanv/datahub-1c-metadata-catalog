from __future__ import annotations

from datahub.metadata.schema_classes import (
    BrowsePathsV2Class,
    ContainerPropertiesClass,
    DataFlowInfoClass,
    DataJobInfoClass,
    DataJobInputOutputClass,
)

from datahub_1c.api.models import IntegrationService
from datahub_1c.mapping.integration_services import (
    build_integration_service_type_folder_workunits,
    build_integration_service_workunits,
    integration_endpoint_job_urn,
    integration_service_flow_urn,
    integration_service_type_folder_urn_for,
)
from datahub_1c.mapping.urn import infobase_container_urn_for


def test_service_type_folder_browse_path() -> None:
    wus = list(
        build_integration_service_type_folder_workunits(
            service_type="HTTPServices",
            infobase_name="1c-test",
            env="DEV",
        )
    )
    folder_urn = integration_service_type_folder_urn_for(
        "HTTPServices",
        infobase_name="1c-test",
        env="DEV",
    )
    props = next(wu for wu in wus if isinstance(wu.metadata.aspect, ContainerPropertiesClass))
    assert props.metadata.entityUrn == folder_urn
    assert props.metadata.aspect.name == "HTTPServices"

    bp = next(wu for wu in wus if isinstance(wu.metadata.aspect, BrowsePathsV2Class))
    assert [entry.urn for entry in bp.metadata.aspect.path] == [
        infobase_container_urn_for(infobase_name="1c-test", env="DEV"),
    ]


def test_http_service_emits_flow_job_metadata_only() -> None:
    service = IntegrationService.model_validate(
        {
            "service_type": "HTTPServices",
            "name": "OrdersApi",
            "full_name": "HTTPService.OrdersApi",
            "root_url": "orders",
            "endpoints": [
                {
                    "endpoint_type": "http_method",
                    "name": "Post",
                    "full_name": "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post",
                    "url_template_name": "Orders",
                    "url_template": "/orders",
                    "method_name": "Post",
                    "http_method": "POST",
                    "handler": "PostOrders",
                    "input_objects": [
                        {
                            "object_type": "Documents",
                            "name": "ЗаказКлиента",
                            "full_name": "Document.ЗаказКлиента",
                            "source": "manual",
                            "confidence": "high",
                        },
                    ],
                },
            ],
        }
    )
    flow_urn = integration_service_flow_urn(
        service_type="HTTPServices",
        service_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        infobase_name="1c-test",
        env="DEV",
    )
    assert ".integration.http." in flow_urn
    endpoint_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    job_urn = integration_endpoint_job_urn(
        flow_urn=flow_urn,
        endpoint_uuid=endpoint_uuid,
        endpoint_type="http_method",
    )
    assert ",method.bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb)" in job_urn
    folder_urn = integration_service_type_folder_urn_for(
        "HTTPServices",
        infobase_name="1c-test",
        env="DEV",
    )

    emission = build_integration_service_workunits(
        service=service,
        service_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        endpoint_uuid_by_full_name={
            "HTTPService.OrdersApi.URLTemplate.Orders.Method.Post": endpoint_uuid,
        },
        object_urn_by_full_name={
            "Document.ЗаказКлиента": "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,1c-test.doc,DEV)",
        },
        infobase_name="1c-test",
        env="DEV",
    )

    aspects = [wu.metadata.aspect for wu in emission.workunits]
    assert any(isinstance(aspect, DataFlowInfoClass) for aspect in aspects)
    jobs = [aspect for aspect in aspects if isinstance(aspect, DataJobInfoClass)]
    assert len(jobs) == 1
    assert jobs[0].flowUrn == flow_urn
    assert jobs[0].customProperties["httpMethod"] == "POST"
    assert jobs[0].customProperties["internalInputDatasetUrns"] == (
        '["urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,1c-test.doc,DEV)"]'
    )
    assert jobs[0].customProperties["internalInputObjectFullNames"] == (
        '["Document.ЗаказКлиента"]'
    )
    assert not any(isinstance(aspect, DataJobInputOutputClass) for aspect in aspects)
    assert emission.endpoints_emitted == 1
    assert emission.internal_inputs_resolved == 1
    assert emission.internal_inputs_unresolved == 0

    browse_paths = {
        wu.metadata.entityUrn: wu.metadata.aspect
        for wu in emission.workunits
        if isinstance(wu.metadata.aspect, BrowsePathsV2Class)
    }
    assert [entry.urn for entry in browse_paths[flow_urn].path] == [
        infobase_container_urn_for(infobase_name="1c-test", env="DEV"),
        folder_urn,
    ]
    assert [entry.urn for entry in browse_paths[job_urn].path] == [
        infobase_container_urn_for(infobase_name="1c-test", env="DEV"),
        folder_urn,
        flow_urn,
    ]


def test_web_service_unresolved_input_is_metadata_hint_only() -> None:
    service = IntegrationService.model_validate(
        {
            "service_type": "WebServices",
            "name": "Exchange",
            "full_name": "WebService.Exchange",
            "endpoints": [
                {
                    "endpoint_type": "web_operation",
                    "name": "Send",
                    "full_name": "WebService.Exchange.Operation.Send",
                    "operation_name": "Send",
                    "input_objects": [
                        {
                            "object_type": "Documents",
                            "name": "НеВScope",
                            "full_name": "Document.НеВScope",
                        },
                    ],
                },
            ],
        }
    )

    emission = build_integration_service_workunits(
        service=service,
        service_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        endpoint_uuid_by_full_name={
            "WebService.Exchange.Operation.Send": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        },
        object_urn_by_full_name={},
        infobase_name="1c-test",
        env="DEV",
    )

    job = next(
        wu.metadata.aspect
        for wu in emission.workunits
        if isinstance(wu.metadata.aspect, DataJobInfoClass)
    )
    assert job.type == "1C_WEB_SERVICE_OPERATION"
    assert job.customProperties["internalInputUnresolvedFullNames"] == '["Document.НеВScope"]'
    assert not any(
        isinstance(wu.metadata.aspect, DataJobInputOutputClass) for wu in emission.workunits
    )
    assert emission.internal_inputs_resolved == 0
    assert emission.internal_inputs_unresolved == 1
