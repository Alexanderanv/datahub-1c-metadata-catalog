"""Эмиссия видо-специфичных аспектов ``oneC*Properties``.

Если API 1С не вернул соответствующий sub-object, аспект не эмитируется.
"""

from __future__ import annotations

from typing import Any

from datahub.ingestion.api.workunit import MetadataWorkUnit

from datahub_1c.api.models import (
    CatalogProperties,
    DocumentProperties,
    RegisterProperties,
)
from datahub_1c.mapping.custom_aspects import (
    ONE_C_CATALOG_PROPERTIES,
    ONE_C_DOCUMENT_PROPERTIES,
    ONE_C_REGISTER_PROPERTIES,
    build_custom_aspect_workunit,
)
from datahub_1c.mapping.urn import ObjectKind


def _payload_from(dto: object, field_map: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for snake, camel in field_map.items():
        value = getattr(dto, snake, None)
        if value is not None:
            out[camel] = value
    return out


_CATALOG_FIELDS: dict[str, str] = {
    "is_hierarchical": "isHierarchical",
    "hierarchy_kind": "hierarchyKind",
    "has_owner": "hasOwner",
    "owner_names": "ownerNames",
    "code_length": "codeLength",
    "description_length": "descriptionLength",
}


def build_catalog_properties_workunit(
    *,
    entity_urn: str,
    properties: CatalogProperties | None,
) -> MetadataWorkUnit | None:
    if properties is None:
        return None
    payload = _payload_from(properties, _CATALOG_FIELDS)
    if not payload:
        return None
    return build_custom_aspect_workunit(
        entity_urn=entity_urn,
        entity_type="dataset",
        aspect_name=ONE_C_CATALOG_PROPERTIES,
        payload=payload,
        workunit_id=f"{entity_urn}-{ONE_C_CATALOG_PROPERTIES}",
    )


_DOCUMENT_FIELDS: dict[str, str] = {
    "is_postable": "isPostable",
    "numerator_name": "numeratorName",
    "numbering_periodicity": "numberingPeriodicity",
    "number_length": "numberLength",
}


def build_document_properties_workunit(
    *,
    entity_urn: str,
    properties: DocumentProperties | None,
) -> MetadataWorkUnit | None:
    if properties is None:
        return None
    payload = _payload_from(properties, _DOCUMENT_FIELDS)
    if not payload:
        return None
    return build_custom_aspect_workunit(
        entity_urn=entity_urn,
        entity_type="dataset",
        aspect_name=ONE_C_DOCUMENT_PROPERTIES,
        payload=payload,
        workunit_id=f"{entity_urn}-{ONE_C_DOCUMENT_PROPERTIES}",
    )


_REGISTER_FIELDS: dict[str, str] = {
    "register_kind": "registerKind",
    "periodicity": "periodicity",
    "write_mode": "writeMode",
    "totals_enabled": "totalsEnabled",
}

_REGISTER_KIND_VALUES: dict[ObjectKind, str] = {
    ObjectKind.INFORMATION_REGISTER: "Information",
    ObjectKind.ACCUMULATION_REGISTER: "Accumulation",
    ObjectKind.ACCOUNTING_REGISTER: "Accounting",
    ObjectKind.CALCULATION_REGISTER: "Calculation",
}


def register_kind_value_for(kind: ObjectKind) -> str | None:
    """Стабильное значение ``oneCRegisterProperties.registerKind`` для вида."""
    return _REGISTER_KIND_VALUES.get(kind)


def build_register_properties_workunit(
    *,
    entity_urn: str,
    properties: RegisterProperties | None,
    register_kind: str | None = None,
) -> MetadataWorkUnit | None:
    if properties is None and register_kind is None:
        return None
    payload = _payload_from(properties, _REGISTER_FIELDS) if properties else {}
    if "registerKind" not in payload and register_kind is not None:
        payload["registerKind"] = register_kind
    # registerKind is required by the PDL aspect. Without it the custom model
    # payload is invalid, so skip the whole aspect instead of emitting a partial
    # register payload that GMS may reject.
    if "registerKind" not in payload:
        return None
    if not payload:
        return None
    return build_custom_aspect_workunit(
        entity_urn=entity_urn,
        entity_type="dataset",
        aspect_name=ONE_C_REGISTER_PROPERTIES,
        payload=payload,
        workunit_id=f"{entity_urn}-{ONE_C_REGISTER_PROPERTIES}",
    )
