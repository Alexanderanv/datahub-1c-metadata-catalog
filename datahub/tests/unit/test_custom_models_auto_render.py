from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PDL_DIR = REPO_ROOT / "custom-models/src/main/pegasus/io/github/alexanderanv/datahub/onec"


def _aspect_metadata(filename: str) -> dict[str, Any]:
    content = (PDL_DIR / filename).read_text(encoding="utf-8")
    marker = "@Aspect"
    start = content.index(marker)
    brace_start = content.index("{", start)
    depth = 0
    for idx in range(brace_start, len(content)):
        char = content[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(content[brace_start : idx + 1])
    raise AssertionError(f"{filename} has an unterminated @Aspect annotation")


def test_onec_custom_aspects_have_selected_datahub_ui_render_specs() -> None:
    expected_rendered = {
        "OneCObjectProperties.pdl": {
            "name": "oneCObjectProperties",
            "autoRender": True,
            "renderSpec": {
                "displayType": "properties",
                "displayName": "Properties 1C",
            },
        },
        "OneCDbMapping.pdl": {
            "name": "oneCDbMapping",
            "autoRender": True,
            "renderSpec": {
                "displayType": "tabular",
                "key": "attributeColumns",
                "displayName": "Column mapping 1C",
            },
        },
    }

    for filename, expected in expected_rendered.items():
        assert _aspect_metadata(filename) == expected


def test_onec_auxiliary_aspects_are_not_auto_rendered() -> None:
    for filename in {
        "OneCCatalogProperties.pdl",
        "OneCDocumentProperties.pdl",
        "OneCRegisterProperties.pdl",
        "OneCDomainRelationships.pdl",
    }:
        aspect = _aspect_metadata(filename)
        assert aspect.get("autoRender") is not True
        assert "renderSpec" not in aspect
