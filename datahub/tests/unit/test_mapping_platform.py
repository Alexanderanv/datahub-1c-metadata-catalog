from __future__ import annotations

from datahub.metadata.schema_classes import DataPlatformInfoClass, PlatformTypeClass

from datahub_1c.mapping.platform import (
    DEFAULT_LOGO_URL,
    PLATFORM_DISPLAY_NAME,
    build_platform_workunit,
)
from datahub_1c.mapping.urn import PLATFORM_1C


class TestBuildPlatformWorkunit:
    def test_targets_platform_urn(self) -> None:
        wu = build_platform_workunit()
        assert wu.metadata.entityUrn == f"urn:li:dataPlatform:{PLATFORM_1C}"

    def test_aspect_contents(self) -> None:
        wu = build_platform_workunit()
        aspect = wu.metadata.aspect
        assert isinstance(aspect, DataPlatformInfoClass)
        assert aspect.name == PLATFORM_1C
        assert aspect.displayName == PLATFORM_DISPLAY_NAME
        assert aspect.type == PlatformTypeClass.OTHERS
        assert aspect.datasetNameDelimiter == "."

    def test_default_logo(self) -> None:
        wu = build_platform_workunit()
        assert wu.metadata.aspect.logoUrl == DEFAULT_LOGO_URL  # type: ignore[union-attr]

    def test_custom_logo(self) -> None:
        wu = build_platform_workunit(logo_url="https://example.com/1c.svg")
        assert wu.metadata.aspect.logoUrl == "https://example.com/1c.svg"  # type: ignore[union-attr]
