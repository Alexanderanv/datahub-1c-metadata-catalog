#!/usr/bin/env python3
"""Run the reference ingestion pipeline for the 1C DataHub extension.

This runner is intentionally small. It performs preflight checks, runs the 1C
source recipe, and optionally runs the standard database recipe on the physical
tables returned by the 1C ``/db-mapping`` API. It does not write directly to the
search index and uses only public DataHub ingestion APIs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATAHUB_DIR = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from pg_tables_pattern import _expand_env, _load_recipe, _source_config  # noqa: E402

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run reference 1C + optional database ingestion.",
    )
    parser.add_argument(
        "--onec-recipe",
        default=os.environ.get(
            "ONEC_RECIPE",
            str(_DATAHUB_DIR.parent / "examples" / "recipes" / "1c-full.dhub.yaml"),
        ),
        help="1C recipe path.",
    )
    parser.add_argument(
        "--db-recipe",
        default=os.environ.get(
            "DB_RECIPE",
            str(_DATAHUB_DIR.parent / "examples" / "recipes" / "db-postgres.dhub.yaml"),
        ),
        help="Database recipe path.",
    )
    parser.add_argument(
        "--datahub-command",
        default=os.environ.get("DATAHUB_COMMAND", "datahub"),
        help="DataHub CLI executable.",
    )
    parser.add_argument(
        "--skip-configdump-check",
        action="store_true",
        help="Do not validate ConfigDumpInfo.xml before ingestion.",
    )
    parser.add_argument(
        "--validate-configdump-scope",
        default=os.environ.get("CONFIGDUMP_VALIDATE_SCOPE", "true"),
        help="Validate selected objects against the 1C API (default: true).",
    )
    parser.add_argument(
        "--skip-custom-models-check",
        action="store_true",
        help="Do not check DataHub /config.models even if custom aspects are enabled.",
    )
    parser.add_argument(
        "--postgres-ingest-enabled",
        default=os.environ.get("POSTGRES_INGEST_ENABLED", "true"),
        help="Run database ingest after 1C ingest (default: true).",
    )
    parser.add_argument(
        "--skip-db-pattern",
        action="store_true",
        help="Use existing POSTGRES_TABLE_PATTERN_ALLOW instead of building it from /db-mapping.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them.",
    )
    return parser.parse_args()


def _as_bool(value: Any, *, default: bool) -> bool:
    expanded = _expand_env(value)
    if expanded is None:
        return default
    if isinstance(expanded, bool):
        return expanded
    normalized = str(expanded).strip().lower()
    if not normalized:
        return default
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return bool(expanded)


def _recipe_uses_custom_aspects(recipe: Mapping[str, Any]) -> bool:
    ingestion = _source_config(recipe).get("ingestion") or {}
    if not isinstance(ingestion, Mapping):
        return True
    return _as_bool(ingestion.get("emit_custom_aspects"), default=True)


def _run_command(
    *,
    label: str,
    command: Sequence[str],
    env: Mapping[str, str],
    dry_run: bool,
) -> int:
    printable = " ".join(command)
    print(f"[reference-ingest] {label}: {printable}")
    if dry_run:
        return 0
    completed = subprocess.run(command, env=dict(env), check=False)
    return completed.returncode


def _capture_command(
    *,
    label: str,
    command: Sequence[str],
    env: Mapping[str, str],
    dry_run: bool,
) -> str:
    printable = " ".join(command)
    print(f"[reference-ingest] {label}: {printable}")
    if dry_run:
        return os.environ.get("POSTGRES_TABLE_PATTERN_ALLOW", "(?!)")
    completed = subprocess.run(
        command,
        env=dict(env),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    return completed.stdout.strip()


def _configdump_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(_SCRIPT_DIR / "validate_configdump.py"),
        "--recipe",
        args.onec_recipe,
    ]
    if _as_bool(args.validate_configdump_scope, default=True):
        command.append("--check-scope")
    return command


def _custom_models_command(env: Mapping[str, str]) -> list[str]:
    return [
        sys.executable,
        str(_SCRIPT_DIR / "check_custom_models.py"),
        "--server",
        env.get("DATAHUB_GMS_URL", "http://localhost:8080"),
    ]


def _pg_pattern_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(_SCRIPT_DIR / "pg_tables_pattern.py"),
        "--recipe",
        args.onec_recipe,
    ]


def _ingest_command(datahub_command: str, recipe_path: str) -> list[str]:
    return [datahub_command, "ingest", "-c", recipe_path]


def run(args: argparse.Namespace, *, env: Mapping[str, str] | None = None) -> int:
    run_env = dict(os.environ if env is None else env)
    onec_recipe = _load_recipe(args.onec_recipe)

    if not args.skip_configdump_check:
        exit_code = _run_command(
            label="validate ConfigDumpInfo.xml",
            command=_configdump_command(args),
            env=run_env,
            dry_run=args.dry_run,
        )
        if exit_code != 0:
            return exit_code

    if _recipe_uses_custom_aspects(onec_recipe) and not args.skip_custom_models_check:
        exit_code = _run_command(
            label="check DataHub custom model",
            command=_custom_models_command(run_env),
            env=run_env,
            dry_run=args.dry_run,
        )
        if exit_code != 0:
            return exit_code

    exit_code = _run_command(
        label="run 1C ingestion",
        command=_ingest_command(args.datahub_command, args.onec_recipe),
        env=run_env,
        dry_run=args.dry_run,
    )
    if exit_code != 0:
        return exit_code

    if not _as_bool(args.postgres_ingest_enabled, default=True):
        print("[reference-ingest] Database ingestion is disabled.")
        return 0

    if not args.skip_db_pattern:
        pattern = _capture_command(
            label="build database table allow-list from /db-mapping",
            command=_pg_pattern_command(args),
            env=run_env,
            dry_run=args.dry_run,
        )
        run_env["POSTGRES_TABLE_PATTERN_ALLOW"] = pattern

    return _run_command(
        label="run database ingestion",
        command=_ingest_command(args.datahub_command, args.db_recipe),
        env=run_env,
        dry_run=args.dry_run,
    )


def main() -> int:
    args = _parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(f"[reference-ingest] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
