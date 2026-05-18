#!/usr/bin/env python3
"""Validate ``ConfigDumpInfo.xml`` before running 1C ingestion.

The 1C connector uses ``ConfigDumpInfo.xml`` as the source of stable metadata
UUIDs. If this file is missing, stale, or exported from another configuration,
ingestion may finish with an incomplete catalog. This script turns that problem
into an explicit preflight failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATAHUB_DIR = _SCRIPT_DIR.parent
_SRC_DIR = _DATAHUB_DIR / "src"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from pg_tables_pattern import (  # noqa: E402
    _expand_env,
    _load_recipe,
    _object_filters,
    _resolve_connection_args,
    _source_config,
)

from datahub_1c.api.client import OneCApiClient  # noqa: E402
from datahub_1c.config import IntegrationServicesConfig  # noqa: E402
from datahub_1c.mapping.metadata_uuid import (  # noqa: E402
    MetadataUuidIndex,
    parse_config_dump_info,
    supported_eng_prefixes,
)
from datahub_1c.mapping.urn import kind_from_plural, spec_for  # noqa: E402

_SKIP_MAX_AGE = {"", "0", "off", "false", "none", "skip"}


@dataclass
class ValidationResult:
    """Result of ``ConfigDumpInfo.xml`` validation."""

    path: Path
    object_uuids: int = 0
    tabular_section_uuids: int = 0
    attribute_uuids: int = 0
    service_uuids: int = 0
    endpoint_uuids: int = 0
    checked_objects: int = 0
    checked_tabular_sections: int = 0
    checked_services: int = 0
    checked_endpoints: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate ConfigDumpInfo.xml used by the 1C DataHub connector.",
    )
    parser.add_argument(
        "--recipe",
        default=os.environ.get(
            "ONEC_RECIPE",
            str(_DATAHUB_DIR.parent / "examples" / "recipes" / "1c-full.dhub.yaml"),
        ),
        help=(
            "Path to the 1C recipe "
            "(default: $ONEC_RECIPE or examples/recipes/1c-full.dhub.yaml)"
        ),
    )
    parser.add_argument(
        "--path",
        default=os.environ.get("ONEC_CONFIG_DUMP_INFO_PATH"),
        help=(
            "Path to ConfigDumpInfo.xml. If omitted, the value is read from "
            "source.config.metadata_uuid_source.config_dump_info_path."
        ),
    )
    parser.add_argument(
        "--max-age-seconds",
        default=os.environ.get("CONFIGDUMP_MAX_AGE_SECONDS", ""),
        help=(
            "Optional freshness limit. Empty/0/off/false/none/skip disables "
            "the age check."
        ),
    )
    parser.add_argument(
        "--check-scope",
        action="store_true",
        help="Query the 1C API and ensure every selected object has UUIDs.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ONEC_BASE_URL"),
        help="1C metadata API URL (default: $ONEC_BASE_URL or recipe).",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("ONEC_USERNAME"),
        help="1C username (default: $ONEC_USERNAME or recipe).",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("ONEC_PASSWORD", ""),
        help="1C password (default: $ONEC_PASSWORD or recipe).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args()


def _resolve_metadata_uuid_path(
    *,
    recipe: Mapping[str, Any],
    explicit_path: str | None,
) -> Path:
    raw_path: Any = explicit_path
    if not raw_path:
        metadata_uuid_source = _source_config(recipe).get("metadata_uuid_source") or {}
        if isinstance(metadata_uuid_source, Mapping):
            raw_path = metadata_uuid_source.get("config_dump_info_path")

    expanded = _expand_env(raw_path)
    if not isinstance(expanded, str) or not expanded.strip():
        raise ValueError(
            "ConfigDumpInfo.xml path is not set. Provide --path, "
            "$ONEC_CONFIG_DUMP_INFO_PATH, or "
            "source.config.metadata_uuid_source.config_dump_info_path.",
        )

    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = _DATAHUB_DIR / path
    return path.resolve()


def _parse_max_age_seconds(value: str | int | None) -> int | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in _SKIP_MAX_AGE:
        return None
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise ValueError(f"max age must be an integer number of seconds, got {value!r}") from exc
    if seconds < 0:
        raise ValueError(f"max age cannot be negative: {seconds}")
    return seconds


def _tabular_sections_enabled(recipe: Mapping[str, Any]) -> bool:
    ingestion = _source_config(recipe).get("ingestion") or {}
    if not isinstance(ingestion, Mapping):
        return True
    value = _expand_env(ingestion.get("tabular_sections"))
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _read_uuid_index(path: Path, result: ValidationResult) -> MetadataUuidIndex | None:
    if not path.exists():
        result.errors.append(f"ConfigDumpInfo.xml not found: {path}")
        return None
    if not path.is_file():
        result.errors.append(f"ConfigDumpInfo.xml path is not a file: {path}")
        return None
    if path.stat().st_size == 0:
        result.errors.append(f"ConfigDumpInfo.xml is empty: {path}")
        return None

    try:
        index = parse_config_dump_info(path)
    except Exception as exc:
        result.errors.append(f"ConfigDumpInfo.xml cannot be parsed: {type(exc).__name__}: {exc}")
        return None

    result.object_uuids = len(index.objects)
    result.tabular_section_uuids = len(index.tabular_sections)
    result.attribute_uuids = len(index.attributes)
    result.service_uuids = len(index.integration_services)
    result.endpoint_uuids = len(index.integration_endpoints)

    if result.object_uuids + result.service_uuids == 0:
        prefixes = ", ".join(supported_eng_prefixes())
        result.errors.append(
            "ConfigDumpInfo.xml does not contain supported 1C metadata objects. "
            f"Expected one of these prefixes: {prefixes}",
        )
    return index


def _check_freshness(
    *,
    path: Path,
    max_age_seconds: int | None,
    result: ValidationResult,
) -> None:
    if max_age_seconds is None or result.errors:
        return
    age_seconds = int(time.time() - path.stat().st_mtime)
    if age_seconds > max_age_seconds:
        result.errors.append(
            "ConfigDumpInfo.xml is older than allowed: "
            f"age={age_seconds}s, max_age={max_age_seconds}s, path={path}",
        )


def _check_object_scope(
    *,
    client: Any,
    recipe: Mapping[str, Any],
    uuid_index: MetadataUuidIndex,
    result: ValidationResult,
) -> None:
    object_filters = _object_filters(recipe)
    tabular_sections_enabled = _tabular_sections_enabled(recipe)
    summaries = client.list_objects(types=object_filters.include_types or None)
    explicit_objects = {
        (object_type, entry.name)
        for object_type, entries in object_filters.include_objects.items()
        if entries
        for entry in entries
    }
    returned_objects: set[tuple[str, str]] = set()

    for summary in summaries:
        if not object_filters.includes_object(summary.object_type, summary.name):
            continue

        returned_objects.add((summary.object_type, summary.name))
        try:
            kind = kind_from_plural(summary.object_type)
        except ValueError:
            result.warnings.append(
                f"1C API returned unsupported object type: {summary.object_type}",
            )
            continue

        result.checked_objects += 1
        if uuid_index.object_uuid(kind, summary.name) is None:
            result.errors.append(
                f"Missing object UUID in ConfigDumpInfo.xml: "
                f"{summary.object_type}.{summary.name}",
            )
            continue

        if not tabular_sections_enabled or not spec_for(kind).supports_tabular_sections:
            continue
        if not object_filters.should_fetch_tabular_sections(summary.object_type, summary.name):
            continue

        selection = object_filters.object_selection(summary.object_type, summary.name)
        returned_tabular_sections: set[str] = set()
        for tabular_part in client.get_tabular_parts(summary.object_type, summary.name):
            returned_tabular_sections.add(tabular_part.name)
            if not object_filters.includes_tabular_section(
                summary.object_type,
                summary.name,
                tabular_part.name,
            ):
                continue
            result.checked_tabular_sections += 1
            if uuid_index.tabular_section_uuid(kind, summary.name, tabular_part.name) is None:
                result.errors.append(
                    f"Missing tabular section UUID in ConfigDumpInfo.xml: "
                    f"{summary.object_type}.{summary.name}.{tabular_part.name}",
                )

        if selection is not None and selection.tabular_sections is not None:
            expected_tabular_sections = set(selection.tabular_sections) - set(
                object_filters.common_filters.tabular_sections,
            )
            for tabular_section_name in sorted(
                expected_tabular_sections - returned_tabular_sections,
            ):
                result.errors.append(
                    f"1C API did not return selected tabular section: "
                    f"{summary.object_type}.{summary.name}.{tabular_section_name}",
                )

    for object_type, object_name in sorted(explicit_objects - returned_objects):
        result.errors.append(
            f"1C API did not return selected object: {object_type}.{object_name}",
        )


def _check_integration_service_scope(
    *,
    client: Any,
    recipe: Mapping[str, Any],
    uuid_index: MetadataUuidIndex,
    result: ValidationResult,
) -> None:
    raw_config = _source_config(recipe).get("integration_services") or {}
    integration_config = IntegrationServicesConfig.model_validate(raw_config)
    if not integration_config.enabled:
        return

    services = client.get_integration_services(
        types=integration_config.include_types or None,
        services=integration_config.service_full_names() or None,
        endpoints=integration_config.endpoint_full_names() or None,
    )

    explicit_services = set(integration_config.service_full_names())
    returned_services = {service.full_name for service in services}
    for full_name in sorted(explicit_services - returned_services):
        result.errors.append(f"1C API did not return selected integration service: {full_name}")

    explicit_endpoints = set(integration_config.endpoint_full_names())
    returned_endpoints: set[str] = set()

    for service in services:
        if not integration_config.includes_service(service.service_type, service.name):
            continue

        result.checked_services += 1
        if uuid_index.integration_service_uuid(service.service_type, service.name) is None:
            result.errors.append(
                f"Missing integration service UUID in ConfigDumpInfo.xml: {service.full_name}",
            )

        for endpoint in service.endpoints:
            if not integration_config.includes_endpoint(
                service.service_type,
                service.name,
                endpoint.full_name,
            ):
                continue
            returned_endpoints.add(endpoint.full_name)
            result.checked_endpoints += 1
            if uuid_index.integration_endpoint_uuid(endpoint.full_name) is None:
                result.errors.append(
                    f"Missing integration endpoint UUID in ConfigDumpInfo.xml: "
                    f"{endpoint.full_name}",
                )

    for full_name in sorted(explicit_endpoints - returned_endpoints):
        result.errors.append(f"1C API did not return selected integration endpoint: {full_name}")


def validate_config_dump(
    *,
    recipe: Mapping[str, Any],
    path: Path,
    max_age_seconds: int | None = None,
    client: Any | None = None,
    check_scope: bool = False,
) -> ValidationResult:
    result = ValidationResult(path=path)
    uuid_index = _read_uuid_index(path, result)
    _check_freshness(path=path, max_age_seconds=max_age_seconds, result=result)

    if uuid_index is None or not check_scope:
        return result

    if client is None:
        raise ValueError("client is required when check_scope=True")

    _check_object_scope(
        client=client,
        recipe=recipe,
        uuid_index=uuid_index,
        result=result,
    )
    _check_integration_service_scope(
        client=client,
        recipe=recipe,
        uuid_index=uuid_index,
        result=result,
    )
    return result


def _result_payload(result: ValidationResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "path": str(result.path),
        "uuid_counts": {
            "objects": result.object_uuids,
            "tabular_sections": result.tabular_section_uuids,
            "attributes": result.attribute_uuids,
            "integration_services": result.service_uuids,
            "integration_endpoints": result.endpoint_uuids,
        },
        "checked_scope": {
            "objects": result.checked_objects,
            "tabular_sections": result.checked_tabular_sections,
            "integration_services": result.checked_services,
            "integration_endpoints": result.checked_endpoints,
        },
        "warnings": result.warnings,
        "errors": result.errors,
    }


def _print_text(result: ValidationResult) -> None:
    status = "OK" if result.ok else "ERROR"
    print(f"[configdump] {status}: {result.path}")
    print(
        "[configdump] UUID index: "
        f"objects={result.object_uuids}, "
        f"tabular_sections={result.tabular_section_uuids}, "
        f"attributes={result.attribute_uuids}, "
        f"integration_services={result.service_uuids}, "
        f"integration_endpoints={result.endpoint_uuids}",
    )
    if result.checked_objects or result.checked_services:
        print(
            "[configdump] Checked recipe scope: "
            f"objects={result.checked_objects}, "
            f"tabular_sections={result.checked_tabular_sections}, "
            f"integration_services={result.checked_services}, "
            f"integration_endpoints={result.checked_endpoints}",
        )
    for warning in result.warnings:
        print(f"[configdump] WARN: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"[configdump] ERROR: {error}", file=sys.stderr)


def main() -> int:
    args = _parse_args()
    try:
        recipe = _load_recipe(args.recipe)
        path = _resolve_metadata_uuid_path(recipe=recipe, explicit_path=args.path)
        max_age_seconds = _parse_max_age_seconds(args.max_age_seconds)

        if args.check_scope:
            base_url, username, password = _resolve_connection_args(
                recipe=recipe,
                base_url=args.base_url,
                username=args.username,
                password=args.password,
            )
            with OneCApiClient(base_url, username, password) as client:
                result = validate_config_dump(
                    recipe=recipe,
                    path=path,
                    max_age_seconds=max_age_seconds,
                    client=client,
                    check_scope=True,
                )
        else:
            result = validate_config_dump(
                recipe=recipe,
                path=path,
                max_age_seconds=max_age_seconds,
            )
    except Exception as exc:
        print(f"[configdump] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(_result_payload(result), ensure_ascii=False, sort_keys=True))
    else:
        _print_text(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
