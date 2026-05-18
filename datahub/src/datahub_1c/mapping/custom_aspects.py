"""Эмиссия кастомных ``oneC*`` аспектов через ``GenericAspectClass``.

DataHub SDK не знает локальные аспекты до установки custom-models в GMS,
поэтому payload сериализуется в JSON bytes. ``ensure_ascii=True`` оставлен
осознанно: GMS ожидает ASCII-escaped value для generic aspect.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    ChangeTypeClass,
    GenericAspectClass,
    MetadataChangeProposalClass,
)

# Имена кастомных аспектов. Должны совпадать 1:1 с теми, что объявлены в
# `custom-models/src/main/pegasus/io/github/alexanderanv/datahub/onec/*.pdl`
# через `@Aspect.name`.
ONE_C_OBJECT_PROPERTIES: str = "oneCObjectProperties"
ONE_C_CATALOG_PROPERTIES: str = "oneCCatalogProperties"
ONE_C_DOCUMENT_PROPERTIES: str = "oneCDocumentProperties"
ONE_C_REGISTER_PROPERTIES: str = "oneCRegisterProperties"
ONE_C_DB_MAPPING: str = "oneCDbMapping"
ONE_C_DOMAIN_RELATIONSHIPS: str = "oneCDomainRelationships"

_JSON_CONTENT_TYPE: str = "application/json"


def _generic_aspect(payload: Mapping[str, Any]) -> GenericAspectClass:
    """Упаковать dict в ``GenericAspectClass`` c JSON-body."""
    data = json.dumps(dict(payload), ensure_ascii=True, separators=(",", ":"))
    return GenericAspectClass(
        value=data.encode("ascii"),
        contentType=_JSON_CONTENT_TYPE,
    )


def build_custom_aspect_workunit(
    *,
    entity_urn: str,
    entity_type: str,
    aspect_name: str,
    payload: Mapping[str, Any],
    workunit_id: str,
) -> MetadataWorkUnit:
    mcp = MetadataChangeProposalClass(
        entityType=entity_type,
        entityUrn=entity_urn,
        aspectName=aspect_name,
        aspect=_generic_aspect(payload),
        changeType=ChangeTypeClass.UPSERT,
    )
    return MetadataWorkUnit(id=workunit_id, mcp_raw=mcp)
