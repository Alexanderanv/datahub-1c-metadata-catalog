"""Эмиссия ``browsePathsV2`` для датасетов и контейнеров 1С.

Путь задаётся явно, чтобы DataHub Navigate не строил виртуальные папки из
``datasetKey.name``.
"""

from __future__ import annotations

from collections.abc import Iterable

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    BrowsePathEntryClass,
    BrowsePathsV2Class,
)


def _entry(urn: str) -> BrowsePathEntryClass:
    """Entry ``browsePathsV2``, ссылающееся на существующий URN."""
    return BrowsePathEntryClass(id=urn, urn=urn)


def build_browse_paths_v2_workunit(
    *,
    entity_urn: str,
    parent_urns: Iterable[str] = (),
) -> MetadataWorkUnit:
    path = [_entry(urn) for urn in parent_urns]
    return MetadataChangeProposalWrapper(
        entityUrn=entity_urn,
        aspect=BrowsePathsV2Class(path=path),
    ).as_workunit()
