from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_reference_docker_context_excludes_local_env_files() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "**/.env" in dockerignore
    assert "**/.env.local" in dockerignore


def test_reference_runner_image_uses_narrow_copy_scope() -> None:
    dockerfile = (
        REPO_ROOT / "deploy/reference/ingestion/Dockerfile"
    ).read_text(encoding="utf-8")

    assert "COPY datahub /app/datahub" not in dockerfile
    assert "COPY datahub/src /app/datahub/src" in dockerfile
    assert "COPY datahub/scripts /app/datahub/scripts" in dockerfile
