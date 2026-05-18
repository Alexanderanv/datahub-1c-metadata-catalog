"""Pydantic-модели ответов REST API сервиса метаданных 1С.

DTO зеркалят OpenAPI-контракт. Для ответов API включён ``extra="ignore"``,
чтобы новые поля сервиса не ломали ingestion.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class HealthResponse(_ApiModel):
    status: str
    version: str | None = None


class MetadataObjectSummary(_ApiModel):
    object_type: str
    name: str
    full_name: str
    synonym: str | None = None


class AttributeType(_ApiModel):
    name: str
    is_reference: bool


class Attribute(_ApiModel):
    name: str
    synonym: str | None = None
    types: list[AttributeType] = Field(default_factory=list)
    max_length: int | None = None
    role: str = "attribute"


class CatalogProperties(_ApiModel):
    is_hierarchical: bool | None = None
    hierarchy_kind: str | None = None
    has_owner: bool | None = None
    owner_names: list[str] | None = None
    code_length: int | None = None
    description_length: int | None = None


class DocumentProperties(_ApiModel):
    is_postable: bool | None = None
    numerator_name: str | None = None
    numbering_periodicity: str | None = None
    number_length: int | None = None


class RegisterProperties(_ApiModel):
    register_kind: str
    periodicity: str | None = None
    write_mode: str | None = None
    totals_enabled: bool | None = None


class MetadataObjectDetail(_ApiModel):
    object_type: str
    name: str
    full_name: str
    synonym: str | None = None
    comment: str | None = None
    attributes: list[Attribute] = Field(default_factory=list)
    catalog_properties: CatalogProperties | None = None
    document_properties: DocumentProperties | None = None
    register_properties: RegisterProperties | None = None


class TabularPart(_ApiModel):
    name: str
    synonym: str | None = None
    attributes: list[Attribute] = Field(default_factory=list)


class Reference(_ApiModel):
    source_object_type: str
    source_name: str
    target_object_type: str
    target_name: str
    source_tabular_part: str | None = None
    source_attribute: str | None = None
    target_attribute: str | None = None


class LineageEdge(_ApiModel):
    upstream_object_type: str
    upstream_name: str
    downstream_object_type: str
    downstream_name: str
    kind: str
    source: str = "metadata"
    confidence: str = "medium"
    description: str | None = None
    details: dict[str, object] | None = None


class IntegrationInputObject(_ApiModel):
    """Внутренняя 1С-связь service operation с объектом метаданных.

    Это не стандартный DataHub lineage; source сохраняет связь как metadata
    на ``DataJob``.
    """

    object_type: str
    name: str
    full_name: str
    source: str = "manual"
    confidence: str = "medium"
    description: str | None = None
    details: dict[str, object] | None = None


class WebServiceParameter(_ApiModel):
    name: str
    direction: str | None = None
    xdto_type: str | None = None
    nillable: bool | None = None


class IntegrationEndpoint(_ApiModel):
    """Endpoint интеграционного сервиса 1С.

    ``endpoint_type`` различает HTTP method и WebService operation. Набор
    остальных полей зависит от типа endpoint-а, поэтому они опциональны.
    """

    endpoint_type: str
    name: str
    full_name: str
    synonym: str | None = None
    comment: str | None = None

    # HTTPService URLTemplate.Method
    url_template_name: str | None = None
    url_template_full_name: str | None = None
    url_template: str | None = None
    method_name: str | None = None
    http_method: str | None = None
    handler: str | None = None

    # WebService Operation
    operation_name: str | None = None
    procedure_name: str | None = None
    transactioned: bool | None = None
    nillable: bool | None = None
    data_lock_control_mode: str | None = None
    return_xdto_type: str | None = None
    parameters: list[WebServiceParameter] = Field(default_factory=list)

    input_objects: list[IntegrationInputObject] = Field(default_factory=list)


class IntegrationService(_ApiModel):
    service_type: str
    name: str
    full_name: str
    synonym: str | None = None
    comment: str | None = None
    endpoints: list[IntegrationEndpoint] = Field(default_factory=list)

    # HTTPService-level properties
    root_url: str | None = None
    reuse_sessions: str | None = None
    session_max_age: int | None = None

    # WebService-level properties
    namespace: str | None = None
    descriptor_file_name: str | None = None


# Назначения таблиц (table_purpose) из ответа /db-mapping.
# Совпадают с enum'ом из openapi.yaml (DbTableMapping.purpose) и c
# `СловарьСоответствийНазначенийТаблицБазыДанных` в Module.bsl.
TABLE_PURPOSE_MAIN: str = "Main"
TABLE_PURPOSE_TABULAR_SECTION: str = "TabularSection"
TABLE_PURPOSE_TOTALS: str = "Totals"
TABLE_PURPOSE_TOTALS_SLICE_FIRST: str = "TotalsSliceFirst"
TABLE_PURPOSE_TOTALS_SLICE_LAST: str = "TotalsSliceLast"

# Назначения колонок (column_purpose) из ответа /db-mapping.
# BSL вычисляет purpose по суффиксу имени физической колонки:
# `_type` → type_discriminator, `_rtref` → reference_discriminator,
# `rref` → reference, остальное → value (см. СобратьМаппингБДПолный).
COLUMN_PURPOSE_VALUE: str = "value"
COLUMN_PURPOSE_TYPE_DISCRIMINATOR: str = "type_discriminator"
COLUMN_PURPOSE_REFERENCE: str = "reference"
COLUMN_PURPOSE_REFERENCE_DISCRIMINATOR: str = "reference_discriminator"


class DbColumn(_ApiModel):
    """Описание одной колонки СУБД в ответе ``/db-mapping``.

    Префикс ``db_`` сохраняет API нейтральным к конкретной СУБД.
    """

    column_name: str
    purpose: str | None = None


class DbColumnMapping(_ApiModel):
    """Маппинг одного реквизита 1С на 1..N колонок СУБД."""

    attribute_name: str
    db_columns: list[DbColumn] = Field(default_factory=list)


class DbTableMapping(_ApiModel):
    """Одна таблица из ``DbMapping.tables``.

    ``tabular_section_name`` заполняется только для
    ``purpose="TabularSection"`` и используется для Sibling с 1С-ТЧ.
    """

    db_table_name: str
    purpose: str
    tabular_section_name: str | None = None
    columns: list[DbColumnMapping] = Field(default_factory=list)


class DbMapping(_ApiModel):
    object_type: str
    name: str
    tables: list[DbTableMapping] = Field(default_factory=list)
