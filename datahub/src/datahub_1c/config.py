"""Pydantic-схема recipe для ``1c-enterprise`` source plugin.

DataHub CLI и Managed Ingestion передают сюда ``source.config``. Модели
нормализуют допустимые YAML-формы, запрещают неизвестные поля и проверяют
контракты, которые нельзя безопасно чинить на этапе эмиссии MCP.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from datahub.ingestion.source.state.stale_entity_removal_handler import (
    StatefulStaleMetadataRemovalConfig,
)
from datahub.ingestion.source.state.stateful_ingestion_base import (
    StatefulIngestionConfigBase,
)
from datahub_1c.mapping.lineage import SUPPORTED_LINEAGE_KINDS
from datahub_1c.mapping.translit import is_ascii_identifier
from datahub_1c.mapping.urn import ObjectKind, kind_from_plural, validate_infobase_name

_SUPPORTED_LINEAGE_KINDS: frozenset[str] = frozenset(SUPPORTED_LINEAGE_KINDS)

INTEGRATION_SERVICE_TYPE_HTTP: str = "HTTPServices"
INTEGRATION_SERVICE_TYPE_WEB: str = "WebServices"
INTEGRATION_SERVICE_TYPES: frozenset[str] = frozenset(
    {
        INTEGRATION_SERVICE_TYPE_HTTP,
        INTEGRATION_SERVICE_TYPE_WEB,
    }
)
_INTEGRATION_SERVICE_SINGULAR: dict[str, str] = {
    INTEGRATION_SERVICE_TYPE_HTTP: "HTTPService",
    INTEGRATION_SERVICE_TYPE_WEB: "WebService",
}


class _StrictModel(BaseModel):
    """BaseModel с запретом неизвестных полей recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class InfobaseConfig(_StrictModel):
    """Информационная база 1С.

    ``name`` входит в dataset/container URN и должен оставаться стабильным.
    """

    name: str = Field(..., min_length=1)
    display_name: str | None = None

    @field_validator("name")
    @classmethod
    def _name_is_stable_id(cls, v: str) -> str:
        return validate_infobase_name(v)

    @field_validator("display_name")
    @classmethod
    def _display_name_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("infobase.display_name must be non-empty if specified")
        return v.strip() if v is not None else None

    @property
    def display(self) -> str:
        return self.display_name or self.name


class TransliterationConfig(_StrictModel):
    """Override-таблица для транслитерации имён 1С."""

    overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def _values_must_be_ascii(cls, v: dict[str, str]) -> dict[str, str]:
        for src, dst in v.items():
            if not dst.isascii():
                raise ValueError(f"transliteration override for {src!r} must be ASCII; got {dst!r}")
            if not dst:
                raise ValueError(f"transliteration override for {src!r} must be non-empty")
            if not is_ascii_identifier(dst):
                raise ValueError(
                    f"transliteration override for {src!r} must match ^[A-Za-z0-9_]+$; "
                    f"got {dst!r}"
                )
        return v


class ObjectSelectionConfig(_StrictModel):
    """Scope одного объекта метаданных 1С."""

    name: str = Field(..., min_length=1)
    ingest_tabular_sections: bool = True
    tabular_sections: list[str] | None = None


class CommonObjectFiltersConfig(_StrictModel):
    """Фильтры, применяемые ко всем выбранным объектам."""

    tabular_sections: list[str] = Field(default_factory=list)


class ObjectFiltersConfig(_StrictModel):
    """Фильтры ingestion по виду, имени объектов и табличным частям.

    ``include_objects`` задаётся по canonical English plural видам 1С.
    Пустое значение означает «все поддерживаемые виды».
    """

    include_objects: dict[str, list[ObjectSelectionConfig]] = Field(
        default_factory=dict,
    )
    common_filters: CommonObjectFiltersConfig = Field(
        default_factory=CommonObjectFiltersConfig,
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_include_objects(cls, data: Any) -> Any:
        """Принять предложенную YAML-форму list-of-maps и compact mapping."""
        if not isinstance(data, Mapping):
            return data

        normalized = dict(data)
        raw_include_objects = normalized.get("include_objects")
        if raw_include_objects is None:
            return normalized

        normalized["include_objects"] = cls._normalize_include_objects_value(
            raw_include_objects,
        )
        return normalized

    @staticmethod
    def _normalize_include_objects_value(
        raw_include_objects: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        by_type: dict[str, list[dict[str, Any]]] = {}

        if isinstance(raw_include_objects, Mapping):
            items = [
                (str(object_type), value) for object_type, value in raw_include_objects.items()
            ]
        elif isinstance(raw_include_objects, Sequence) and not isinstance(raw_include_objects, str):
            items = []
            for item in raw_include_objects:
                if not isinstance(item, Mapping) or len(item) != 1:
                    raise ValueError(
                        "object_filters.include_objects list items must be "
                        "single-key mappings like {Documents: [...]}"
                    )
                object_type, value = next(iter(item.items()))
                items.append((str(object_type), value))
        else:
            raise ValueError(
                "object_filters.include_objects must be a mapping or a list of single-key mappings"
            )

        for object_type, raw_entries in items:
            kind_from_plural(object_type)
            entries = ObjectFiltersConfig._normalize_object_entries(
                object_type=object_type,
                raw_entries=raw_entries,
            )
            existing = by_type.setdefault(object_type, [])
            seen = {entry["name"] for entry in existing}
            for entry in entries:
                if entry["name"] in seen:
                    raise ValueError(
                        f"duplicate object filter entry for {object_type}.{entry['name']}"
                    )
                seen.add(entry["name"])
                existing.append(entry)

        return by_type

    @staticmethod
    def _normalize_object_entries(
        *,
        object_type: str,
        raw_entries: Any,
    ) -> list[dict[str, Any]]:
        if raw_entries is None:
            return []
        if isinstance(raw_entries, str):
            return [{"name": raw_entries}]
        if not isinstance(raw_entries, Sequence):
            raise ValueError(f"object_filters.include_objects.{object_type} must be a list")

        entries: list[dict[str, Any]] = []
        for raw_entry in raw_entries:
            if isinstance(raw_entry, str):
                entries.append({"name": raw_entry})
                continue
            if not isinstance(raw_entry, Mapping):
                raise ValueError(
                    "object filter entries must be strings, mappings with "
                    "`name`, or single-key mappings with object name"
                )
            if "name" in raw_entry:
                entries.append(dict(raw_entry))
                continue
            if len(raw_entry) != 1:
                raise ValueError(
                    "object filter mapping without `name` must have exactly "
                    "one key: the object name"
                )
            object_name, raw_options = next(iter(raw_entry.items()))
            if raw_options is None:
                options: dict[str, Any] = {}
            elif isinstance(raw_options, Mapping):
                options = dict(raw_options)
            else:
                raise ValueError(
                    "object filter options must be a mapping or null for "
                    f"{object_type}.{object_name}"
                )
            options["name"] = str(object_name)
            entries.append(options)

        return entries

    @field_validator("include_objects")
    @classmethod
    def _include_objects_have_valid_kinds(
        cls,
        v: dict[str, list[ObjectSelectionConfig]],
    ) -> dict[str, list[ObjectSelectionConfig]]:
        """Имена видов должны соответствовать известному маппингу множественных форм."""
        for object_type in v:
            kind_from_plural(object_type)
        return v

    @property
    def include_types(self) -> list[str]:
        """Виды объектов для API ``/objects``; пусто = не фильтровать API."""
        return list(self.include_objects)

    def object_kinds(self) -> list[ObjectKind]:
        if not self.include_objects:
            return list(ObjectKind)
        return [kind_from_plural(t) for t in self.include_objects]

    def includes_object(self, object_type: str, object_name: str) -> bool:
        if not self.include_objects:
            return True
        entries = self.include_objects.get(object_type)
        if entries is None:
            return False
        if not entries:
            return True
        return any(entry.name == object_name for entry in entries)

    def object_selection(
        self,
        object_type: str,
        object_name: str,
    ) -> ObjectSelectionConfig | None:
        if not self.includes_object(object_type, object_name):
            return None
        entries = self.include_objects.get(object_type)
        if not entries:
            return ObjectSelectionConfig(name=object_name)
        for entry in entries:
            if entry.name == object_name:
                return entry
        return None

    def should_fetch_tabular_sections(
        self,
        object_type: str,
        object_name: str,
    ) -> bool:
        selection = self.object_selection(object_type, object_name)
        return selection is not None and selection.ingest_tabular_sections

    def includes_tabular_section(
        self,
        object_type: str,
        object_name: str,
        tabular_section_name: str,
    ) -> bool:
        if tabular_section_name in self.common_filters.tabular_sections:
            return False
        selection = self.object_selection(object_type, object_name)
        if selection is None or not selection.ingest_tabular_sections:
            return False
        if selection.tabular_sections is None:
            return True
        return tabular_section_name in selection.tabular_sections


class IngestionOptionsConfig(_StrictModel):
    """Флаги уровня детализации ingestion.

    ``lineage_kinds=None`` означает все поддерживаемые виды, пустой список
    оставляет lineage проход без новых связей. ``emit_db_siblings=False``
    допустим только если остаётся другая DB-связь через кастомные аспекты.
    """

    attributes: bool = True
    tabular_sections: bool = True
    lineage: bool = True
    lineage_kinds: list[str] | None = None
    column_lineage: bool = False
    # По умолчанию отключено: эмиссия PG-слоя включается явно при готовности
    # к работе с DB mapping. Если `postgres.database` не задан, source
    # использует `infobase.name` как DB namespace.
    db_mapping: bool = False
    emit_db_siblings: bool = True
    emit_custom_aspects: bool = True

    @field_validator("lineage_kinds")
    @classmethod
    def _lineage_kinds_are_supported(
        cls,
        v: list[str] | None,
    ) -> list[str] | None:
        if v is None:
            return None

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_kind in v:
            kind = raw_kind.strip()
            if not kind:
                raise ValueError("ingestion.lineage_kinds cannot contain empty values")
            if kind not in _SUPPORTED_LINEAGE_KINDS:
                supported = ", ".join(SUPPORTED_LINEAGE_KINDS)
                raise ValueError(
                    f"unsupported ingestion.lineage_kinds value {kind!r}; "
                    f"supported values: {supported}"
                )
            if kind in seen:
                raise ValueError(f"duplicate ingestion.lineage_kinds value {kind!r}")
            seen.add(kind)
            normalized.append(kind)
        return normalized

    @model_validator(mode="after")
    def _ingestion_options_are_consistent(self) -> IngestionOptionsConfig:
        if self.column_lineage and not self.lineage:
            raise ValueError(
                "column_lineage=True requires lineage=True — "
                "column-level lineage не имеет смысла без dataset-level"
            )
        if self.lineage_kinds is not None and not self.lineage:
            raise ValueError(
                "lineage_kinds can be specified only when lineage=True — "
                "use lineage=False to disable the whole lineage pass"
            )
        if self.db_mapping and not self.emit_db_siblings and not self.emit_custom_aspects:
            raise ValueError(
                "emit_db_siblings=False with db_mapping=True requires "
                "emit_custom_aspects=True so oneCDbMapping/MapsToDbTable remain "
                "as the 1C↔DB link"
            )
        return self

    @property
    def effective_lineage_kinds(self) -> tuple[str, ...]:
        """Виды lineage, которые source должен запросить и эмитить."""
        if not self.lineage:
            return ()
        if self.lineage_kinds is None:
            return SUPPORTED_LINEAGE_KINDS
        return tuple(self.lineage_kinds)


class IntegrationServiceSelectionConfig(_StrictModel):
    """Scope одного HTTP/Web-сервиса 1С."""

    name: str = Field(..., min_length=1)
    endpoints: list[str] | None = None


class IntegrationServicesConfig(_StrictModel):
    """Opt-in scope интеграционных сервисов 1С.

    Отдельная секция нужна потому, что HTTP/Web-сервисы не являются
    dataset-like объектами и эмитятся как ``DataFlow``/``DataJob``.
    """

    include_services: dict[str, list[IntegrationServiceSelectionConfig]] = Field(
        default_factory=dict,
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_include_services(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data

        normalized = dict(data)
        raw_include_services = normalized.get("include_services")
        if raw_include_services is None:
            return normalized

        normalized["include_services"] = cls._normalize_include_services_value(
            raw_include_services,
        )
        return normalized

    @staticmethod
    def _normalize_include_services_value(
        raw_include_services: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        by_type: dict[str, list[dict[str, Any]]] = {}

        if isinstance(raw_include_services, Mapping):
            items = [
                (str(service_type), value) for service_type, value in raw_include_services.items()
            ]
        elif isinstance(raw_include_services, Sequence) and not isinstance(
            raw_include_services, str
        ):
            items = []
            for item in raw_include_services:
                if not isinstance(item, Mapping) or len(item) != 1:
                    raise ValueError(
                        "integration_services.include_services list items must be "
                        "single-key mappings like {HTTPServices: [...]}"
                    )
                service_type, value = next(iter(item.items()))
                items.append((str(service_type), value))
        else:
            raise ValueError(
                "integration_services.include_services must be a mapping or a "
                "list of single-key mappings"
            )

        for service_type, raw_entries in items:
            IntegrationServicesConfig._validate_service_type(service_type)
            entries = IntegrationServicesConfig._normalize_service_entries(
                service_type=service_type,
                raw_entries=raw_entries,
            )
            existing = by_type.setdefault(service_type, [])
            seen = {entry["name"] for entry in existing}
            for entry in entries:
                if entry["name"] in seen:
                    raise ValueError(
                        "duplicate integration service filter entry for "
                        f"{service_type}.{entry['name']}"
                    )
                seen.add(entry["name"])
                existing.append(entry)

        return by_type

    @staticmethod
    def _normalize_service_entries(
        *,
        service_type: str,
        raw_entries: Any,
    ) -> list[dict[str, Any]]:
        if raw_entries is None:
            return []
        if isinstance(raw_entries, str):
            return [{"name": raw_entries}]
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, str):
            raise ValueError(f"integration_services.include_services.{service_type} must be a list")

        entries: list[dict[str, Any]] = []
        for raw_entry in raw_entries:
            if isinstance(raw_entry, str):
                entries.append({"name": raw_entry})
                continue
            if not isinstance(raw_entry, Mapping):
                raise ValueError(
                    "integration service filter entries must be strings, mappings "
                    "with `name`, or single-key mappings with service name"
                )
            if "name" in raw_entry:
                entries.append(dict(raw_entry))
                continue
            if len(raw_entry) != 1:
                raise ValueError(
                    "integration service filter mapping without `name` must have "
                    "exactly one key: the service name"
                )
            service_name, raw_options = next(iter(raw_entry.items()))
            if raw_options is None:
                options: dict[str, Any] = {}
            elif isinstance(raw_options, Mapping):
                options = dict(raw_options)
            else:
                raise ValueError(
                    "integration service filter options must be a mapping or null "
                    f"for {service_type}.{service_name}"
                )
            options["name"] = str(service_name)
            entries.append(options)

        return entries

    @field_validator("include_services")
    @classmethod
    def _include_services_have_valid_types(
        cls,
        v: dict[str, list[IntegrationServiceSelectionConfig]],
    ) -> dict[str, list[IntegrationServiceSelectionConfig]]:
        for service_type in v:
            cls._validate_service_type(service_type)
        return v

    @staticmethod
    def _validate_service_type(service_type: str) -> None:
        if service_type not in INTEGRATION_SERVICE_TYPES:
            raise ValueError(
                "unknown 1C integration service type: "
                f"{service_type!r}; expected one of {sorted(INTEGRATION_SERVICE_TYPES)!r}"
            )

    @property
    def enabled(self) -> bool:
        return bool(self.include_services)

    @property
    def include_types(self) -> list[str]:
        return list(self.include_services)

    def service_full_names(self) -> list[str]:
        """Full names для параметра ``services`` API 1С.

        Если для вида задан wildcard (`HTTPServices: []`), сервисы этого вида
        не перечисляются поимённо: API получает только ``types``.
        """
        result: list[str] = []
        for service_type, entries in self.include_services.items():
            singular = _INTEGRATION_SERVICE_SINGULAR[service_type]
            for entry in entries:
                result.append(f"{singular}.{entry.name}")
        return result

    def endpoint_full_names(self) -> list[str]:
        result: list[str] = []
        for entries in self.include_services.values():
            for entry in entries:
                if entry.endpoints:
                    result.extend(entry.endpoints)
        return result

    def includes_service(self, service_type: str, name: str) -> bool:
        if not self.include_services:
            return False
        entries = self.include_services.get(service_type)
        if entries is None:
            return False
        if not entries:
            return True
        return any(entry.name == name for entry in entries)

    def includes_endpoint(
        self,
        service_type: str,
        service_name: str,
        endpoint_full_name: str,
    ) -> bool:
        entries = self.include_services.get(service_type)
        if entries is None:
            return False
        if not entries:
            return True
        for entry in entries:
            if entry.name != service_name:
                continue
            if entry.endpoints is None:
                return True
            return endpoint_full_name in entry.endpoints
        return False


class MetadataUuidSourceConfig(_StrictModel):
    """Источник стабильных UUID объектов метаданных 1С.

    Сейчас поддержан путь к ``ConfigDumpInfo.xml``. Файл проверяется на
    старте, потому что UUID входит в URN dataset/container.
    """

    config_dump_info_path: Path

    @field_validator("config_dump_info_path")
    @classmethod
    def _path_exists_and_is_file(cls, v: Path) -> Path:
        # Расширяем `~` чтобы можно было писать в recipe `~/.cache/...`.
        expanded = v.expanduser()
        if not expanded.exists():
            raise ValueError(
                f"metadata_uuid_source.config_dump_info_path={expanded!s} "
                "не существует. Проверь путь к ConfigDumpInfo.xml в recipe."
            )
        if not expanded.is_file():
            raise ValueError(
                f"metadata_uuid_source.config_dump_info_path={expanded!s} не является файлом."
            )
        return expanded


class PostgresDbConfig(_StrictModel):
    """Параметры физического Postgres/DB-слоя 1С.

    При ``ingestion.db_mapping=True`` source-плагин эмитит для каждого
    таблицы из ``/db-mapping`` PG-датасет с URN
    ``<database>.<schema>.<table>``. ``platform_instance`` зарезервирован,
    но сейчас не участвует в построении URN.
    """

    database: str | None = None
    schema_name: str = Field(default="public", alias="schema")
    env: str | None = None
    platform_instance: str | None = None

    @field_validator("database")
    @classmethod
    def _database_non_empty_if_set(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("postgres.database must be non-empty if specified")
        return v


class OneCSourceConfig(
    StatefulIngestionConfigBase[StatefulStaleMetadataRemovalConfig],
    _StrictModel,
):
    """Корневая pydantic-схема ``source.config`` для 1C-плагина."""

    base_url: AnyHttpUrl
    username: str = Field(..., min_length=1)
    password: SecretStr

    env: str = Field(default="PROD", min_length=1)
    infobase: InfobaseConfig

    transliteration: TransliterationConfig = Field(default_factory=TransliterationConfig)
    object_filters: ObjectFiltersConfig = Field(default_factory=ObjectFiltersConfig)
    integration_services: IntegrationServicesConfig = Field(
        default_factory=IntegrationServicesConfig,
    )
    ingestion: IngestionOptionsConfig = Field(default_factory=IngestionOptionsConfig)
    postgres: PostgresDbConfig = Field(default_factory=PostgresDbConfig)
    metadata_uuid_source: MetadataUuidSourceConfig
    stateful_ingestion: StatefulStaleMetadataRemovalConfig | None = Field(
        default=None,
        description=(
            "Stateful ingestion settings. When enabled, the source soft-deletes "
            "1C-owned entities that were present in the previous successful run "
            "but are absent from the current recipe/API selection."
        ),
    )

    def pg_env(self) -> str:
        """Фактический env для PG URN: явный override или основной env."""
        return self.postgres.env or self.env

    def pg_database(self) -> str:
        """Фактическая DB namespace для PG/DB URN.

        Если ``postgres.database`` не задан, используется ``infobase.name``.
        """
        return self.postgres.database or self.infobase.name
