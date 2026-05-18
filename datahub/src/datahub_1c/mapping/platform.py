"""Эмиссия аспекта ``dataPlatformInfo`` для платформы ``1c-enterprise``."""

from __future__ import annotations

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    DataPlatformInfoClass,
    PlatformTypeClass,
)

from datahub_1c.mapping.urn import PLATFORM_1C, platform_urn

PLATFORM_DISPLAY_NAME: str = "1C:Enterprise"

# Favicon 1С вместо прозрачного default_logo.svg из datahub-web-react.
DEFAULT_LOGO_URL: str = "https://1c.ru/favicon.ico"


def build_platform_workunit(
    *,
    logo_url: str | None = None,
) -> MetadataWorkUnit:
    aspect = DataPlatformInfoClass(
        name=PLATFORM_1C,
        type=PlatformTypeClass.OTHERS,
        datasetNameDelimiter=".",
        displayName=PLATFORM_DISPLAY_NAME,
        logoUrl=logo_url or DEFAULT_LOGO_URL,
    )
    mcp = MetadataChangeProposalWrapper(
        entityUrn=platform_urn(),
        aspect=aspect,
    )
    return mcp.as_workunit()
