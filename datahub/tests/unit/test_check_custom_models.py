from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).parents[2] / "scripts" / "check_custom_models.py"
    spec = importlib.util.spec_from_file_location("check_custom_models", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fetch_config_adds_bearer_token(monkeypatch) -> None:
    module = _load_script_module()
    seen_headers: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"models": {"registry": "custom-onec", "version": "0.1.0"}}'

    def fake_urlopen(request, timeout):
        assert timeout == 10
        seen_headers.update(dict(request.header_items()))
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    data = module._fetch_config("http://gms", "secret-token")  # noqa: SLF001

    assert data["models"]["registry"] == "custom-onec"
    assert seen_headers["Authorization"] == "Bearer secret-token"
