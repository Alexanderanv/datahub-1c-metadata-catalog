from __future__ import annotations

import json

from datahub.metadata.schema_classes import ChangeTypeClass, MetadataChangeProposalClass

from datahub_1c.mapping.custom_aspects import (
    ONE_C_OBJECT_PROPERTIES,
    build_custom_aspect_workunit,
)

DATASET_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:1c-enterprise,"
    "Document.PostuplenieTovarov,PROD)"
)


class TestBuildCustomAspectWorkunit:
    def _wu(self, payload: dict) -> MetadataChangeProposalClass:
        wu = build_custom_aspect_workunit(
            entity_urn=DATASET_URN,
            entity_type="dataset",
            aspect_name=ONE_C_OBJECT_PROPERTIES,
            payload=payload,
            workunit_id="test-1",
        )
        mcp = wu.metadata
        assert isinstance(mcp, MetadataChangeProposalClass)
        return mcp

    def test_entity_and_aspect_are_set(self) -> None:
        mcp = self._wu({"objectKind": "Документ", "fullName": "Документ.ПоступлениеТоваров"})
        assert mcp.entityUrn == DATASET_URN
        assert mcp.entityType == "dataset"
        assert mcp.aspectName == ONE_C_OBJECT_PROPERTIES
        assert mcp.changeType == ChangeTypeClass.UPSERT

    def test_payload_encoded_as_ascii_json(self) -> None:
        """Cyrillic поля сохраняются как \\uXXXX-escaped — это требование GMS."""
        mcp = self._wu({
            "objectKind": "Документ",
            "fullName": "Документ.ПоступлениеТоваров",
            "synonym": "Поступление товаров",
        })
        raw = mcp.aspect.value  # type: ignore[union-attr]
        assert isinstance(raw, bytes)
        assert raw.isascii()
        decoded = json.loads(raw.decode("ascii"))
        assert decoded["objectKind"] == "Документ"
        assert decoded["synonym"] == "Поступление товаров"

    def test_content_type_is_json(self) -> None:
        mcp = self._wu({"x": 1})
        assert mcp.aspect.contentType == "application/json"  # type: ignore[union-attr]

    def test_workunit_id_preserved(self) -> None:
        wu = build_custom_aspect_workunit(
            entity_urn=DATASET_URN,
            entity_type="dataset",
            aspect_name=ONE_C_OBJECT_PROPERTIES,
            payload={"objectKind": "Документ"},
            workunit_id="mcp-dataset-Document.PostuplenieTovarov-oneCObjectProperties",
        )
        assert wu.id == "mcp-dataset-Document.PostuplenieTovarov-oneCObjectProperties"

    def test_json_is_compact(self) -> None:
        """Separators=(',', ':') — чтобы не увеличивать размер payload."""
        mcp = self._wu({"a": 1, "b": 2})
        assert b", " not in mcp.aspect.value  # type: ignore[union-attr]
        assert b": " not in mcp.aspect.value  # type: ignore[union-attr]
