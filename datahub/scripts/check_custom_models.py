#!/usr/bin/env python3
"""Check that the 1C custom metamodel plugin is loaded by DataHub GMS."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _contains_exact(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(
            str(key) == needle or _contains_exact(child, needle)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_exact(item, needle) for item in value)
    return isinstance(value, str) and value == needle


def _fetch_config(server: str, token: str | None) -> dict[str, Any]:
    url = f"{server.rstrip('/')}/config"
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected /config response type: {type(data).__name__}")
    return data


def _summarize_models(models: Any) -> str:
    if models in (None, {}, []):
        return "{}"
    return json.dumps(models, ensure_ascii=False, indent=2, sort_keys=True)


def _check_once(
    server: str,
    registry_id: str,
    version: str,
    token: str | None,
) -> tuple[bool, str]:
    config = _fetch_config(server, token)
    models = config.get("models")
    has_registry = _contains_exact(models, registry_id)
    has_version = _contains_exact(models, version)

    if has_registry and has_version:
        return True, _summarize_models(models)

    missing = []
    if not has_registry:
        missing.append(f"registry id {registry_id!r}")
    if not has_version:
        missing.append(f"version {version!r}")
    return False, (
        "Missing "
        + " and ".join(missing)
        + " in /config.models:\n"
        + _summarize_models(models)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://localhost:8080")
    parser.add_argument(
        "--token",
        default=os.environ.get("DATAHUB_GMS_TOKEN") or None,
        help="Bearer token for secured DataHub GMS.",
    )
    parser.add_argument("--registry-id", default="custom-onec")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument(
        "--timeout",
        type=float,
        default=0,
        help="Seconds to wait for GMS restart and model loading.",
    )
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()

    deadline = time.monotonic() + max(args.timeout, 0)
    last_error = ""

    while True:
        try:
            ok, details = _check_once(
                args.server,
                args.registry_id,
                args.version,
                args.token,
            )
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            ok = False
            details = f"{type(exc).__name__}: {exc}"

        if ok:
            print(
                "[custom-models] OK: "
                f"{args.registry_id} {args.version} is present in {args.server}/config"
            )
            print(details)
            return 0

        last_error = details
        if time.monotonic() >= deadline:
            break
        print(f"[custom-models] waiting: {details}", file=sys.stderr)
        time.sleep(args.interval)

    print(
        "[custom-models] ERROR: custom metamodel is not loaded by DataHub GMS.",
        file=sys.stderr,
    )
    print(last_error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
