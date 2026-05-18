"""Сборка ``schemaMetadata`` для объектов 1С и табличных частей.

Контракт раскладки: стандартные реквизиты из локального справочника идут
первыми, пользовательские реквизиты из API добавляются после них. API-поля
с ``role="standard"`` игнорируются, чтобы не получить дубли на разных
версиях 1С. Для ``schemaMetadata.platform`` используется URN платформы,
а не строковое имя.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    BooleanTypeClass,
    DateTypeClass,
    ForeignKeyConstraintClass,
    NumberTypeClass,
    OtherSchemaClass,
    RecordTypeClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    UnionTypeClass,
)

from datahub_1c.api.models import Attribute, AttributeType
from datahub_1c.mapping.standard_attributes import (
    StandardAttribute,
    attributes_for,
    attributes_for_tabular_section,
    pick_label,
)
from datahub_1c.mapping.translit import transliterate
from datahub_1c.mapping.urn import ObjectKind, platform_urn

SCHEMA_VERSION: int = 0
SCHEMA_HASH: str = ""  # DataHub требует непустую строку для `hash`? нет — тип str, пустая ok.


# Маппинг имён примитивных типов 1С → DataHub type class.
# Значение — фабрика, возвращающая Any (DataHub SDK не типизирует
# конструкторы *TypeClass как typed callables, поэтому Any — самое
# честное, что мы можем сказать mypy без type: ignore).
_PRIMITIVE_TYPE_MAP: Mapping[str, Any] = {
    "Строка": StringTypeClass,
    "String": StringTypeClass,
    "Число": NumberTypeClass,
    "Number": NumberTypeClass,
    "Дата": DateTypeClass,
    "Date": DateTypeClass,
    "Булево": BooleanTypeClass,
    "Boolean": BooleanTypeClass,
    "УникальныйИдентификатор": StringTypeClass,
    "UUID": StringTypeClass,
}


def _map_primitive_type(name: str) -> Any:
    """Неизвестные имена маппим в ``StringTypeClass``; исходный тип всё равно
    остаётся в ``nativeDataType``.
    """
    cls = _PRIMITIVE_TYPE_MAP.get(name, StringTypeClass)
    return cls()


def _datahub_type_for(types: Sequence[AttributeType]) -> SchemaFieldDataTypeClass:
    """Определить ``SchemaFieldDataType`` для массива типов из API.

    * один тип, не reference → примитив по таблице;
    * один тип, reference → ``RecordTypeClass``;
    * несколько типов → ``UnionTypeClass`` (составной тип 1С).
    """
    if not types:
        return SchemaFieldDataTypeClass(type=StringTypeClass())  # type: ignore[no-untyped-call]
    if len(types) > 1:
        return SchemaFieldDataTypeClass(type=UnionTypeClass())
    only = types[0]
    if only.is_reference:
        return SchemaFieldDataTypeClass(type=RecordTypeClass())  # type: ignore[no-untyped-call]
    return SchemaFieldDataTypeClass(type=_map_primitive_type(only.name))


def _native_type(types: Sequence[AttributeType]) -> str:
    """``SchemaField.nativeDataType`` — человекочитаемое представление
    исходного типа 1С; для составного — через ``" | "``."""
    if not types:
        return ""
    return " | ".join(t.name for t in types)


def _standard_field(
    attr: StandardAttribute,
    *,
    object_name: str,
) -> SchemaFieldClass:
    return SchemaFieldClass(
        fieldPath=attr.field_path,
        type=SchemaFieldDataTypeClass(type=_map_primitive_type(attr.native_data_type)),
        nativeDataType=attr.native_data_type,
        label=pick_label(attr, object_name=object_name),
        description=attr.description_ru,
        nullable=False,
        isPartOfKey=attr.is_part_of_key,
    )


def _user_field(
    attr: Attribute,
    *,
    overrides: Mapping[str, str] | None,
) -> SchemaFieldClass:
    """Имя поля транслитерируется; ``label`` и (при отличии) ``description``
    сохраняют оригинал с кириллицей.
    """
    field_path = transliterate(attr.name, overrides=overrides)
    label = attr.synonym or attr.name
    description = label if label != field_path else None
    return SchemaFieldClass(
        fieldPath=field_path,
        type=_datahub_type_for(attr.types),
        nativeDataType=_native_type(attr.types),
        label=label,
        description=description,
        nullable=False,
        isPartOfKey=False,
    )


def build_schema_fields(
    *,
    standard_attrs: Sequence[StandardAttribute],
    user_attrs: Sequence[Attribute],
    object_name: str,
    overrides: Mapping[str, str] | None = None,
) -> list[SchemaFieldClass]:
    """Устраняет дубликаты: если API прислал реквизит, имя которого после
    транслитерации совпадает со стандартным ``field_path`` — считаем,
    что это та же самая стандартная колонка, и пользовательскую
    пропускаем (справочник точнее).
    """
    taken: set[str] = set()
    fields: list[SchemaFieldClass] = []

    for std in standard_attrs:
        fields.append(_standard_field(std, object_name=object_name))
        taken.add(std.field_path)

    for attr in user_attrs:
        if attr.role == "standard":
            continue
        field_path = transliterate(attr.name, overrides=overrides)
        if field_path in taken:
            continue
        fields.append(_user_field(attr, overrides=overrides))
        taken.add(field_path)

    return fields


def build_schema_metadata_workunit(
    *,
    dataset_urn: str,
    dataset_name: str,
    kind: ObjectKind,
    object_name: str,
    user_attributes: Sequence[Attribute],
    overrides: Mapping[str, str] | None = None,
    is_tabular_section: bool = False,
    foreign_keys: Iterable[ForeignKeyConstraintClass] | None = None,
) -> MetadataWorkUnit:
    standard_attrs = (
        attributes_for_tabular_section() if is_tabular_section
        else attributes_for(kind)
    )
    fields = build_schema_fields(
        standard_attrs=standard_attrs,
        user_attrs=user_attributes,
        object_name=object_name,
        overrides=overrides,
    )
    primary_keys = [f.fieldPath for f in fields if f.isPartOfKey]
    aspect = SchemaMetadataClass(
        schemaName=dataset_name,
        platform=platform_urn(),
        version=SCHEMA_VERSION,
        hash=SCHEMA_HASH,
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=fields,
        primaryKeys=primary_keys or None,
        foreignKeys=list(foreign_keys) if foreign_keys else None,
    )
    return MetadataChangeProposalWrapper(entityUrn=dataset_urn, aspect=aspect).as_workunit()
