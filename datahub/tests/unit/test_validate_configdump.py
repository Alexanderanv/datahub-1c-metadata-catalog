from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_script_module():
    script_path = Path(__file__).parents[2] / "scripts" / "validate_configdump.py"
    spec = importlib.util.spec_from_file_location("validate_configdump", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_configdump(path: Path, entries: list[tuple[str, str]]) -> None:
    lines = ["<ConfigVersions>"]
    lines.extend(f'  <Metadata name="{name}" id="{uuid}"/>' for name, uuid in entries)
    lines.append("</ConfigVersions>")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_validate_configdump_checks_recipe_scope(tmp_path: Path) -> None:
    module = _load_script_module()
    xml_path = tmp_path / "ConfigDumpInfo.xml"
    _write_configdump(
        xml_path,
        [
            ("Document.ЗаказПокупателя", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            (
                "Document.ЗаказПокупателя.TabularSection.Товары",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            ),
            ("HTTPService.Chatbot", "cccccccc-cccc-cccc-cccc-cccccccccccc"),
            (
                "HTTPService.Chatbot.URLTemplate.root.Method.GET",
                "dddddddd-dddd-dddd-dddd-dddddddddddd",
            ),
        ],
    )
    recipe = {
        "source": {
            "config": {
                "object_filters": {
                    "include_objects": {
                        "Documents": ["ЗаказПокупателя"],
                    },
                },
                "integration_services": {
                    "include_services": {
                        "HTTPServices": ["Chatbot"],
                    },
                },
            },
        },
    }

    class FakeClient:
        def list_objects(self, *, types):
            assert types == ["Documents"]
            return [
                SimpleNamespace(object_type="Documents", name="ЗаказПокупателя"),
            ]

        def get_tabular_parts(self, object_type, name):
            assert (object_type, name) == ("Documents", "ЗаказПокупателя")
            return [SimpleNamespace(name="Товары")]

        def get_integration_services(self, *, types, services, endpoints):
            assert types == ["HTTPServices"]
            assert services == ["HTTPService.Chatbot"]
            assert endpoints is None
            return [
                SimpleNamespace(
                    service_type="HTTPServices",
                    name="Chatbot",
                    full_name="HTTPService.Chatbot",
                    endpoints=[
                        SimpleNamespace(
                            full_name="HTTPService.Chatbot.URLTemplate.root.Method.GET",
                        ),
                    ],
                ),
            ]

    result = module.validate_config_dump(
        recipe=recipe,
        path=xml_path,
        client=FakeClient(),
        check_scope=True,
    )

    assert result.ok
    assert result.checked_objects == 1
    assert result.checked_tabular_sections == 1
    assert result.checked_services == 1
    assert result.checked_endpoints == 1


def test_validate_configdump_reports_missing_tabular_section_uuid(tmp_path: Path) -> None:
    module = _load_script_module()
    xml_path = tmp_path / "ConfigDumpInfo.xml"
    _write_configdump(
        xml_path,
        [
            ("Document.ЗаказПокупателя", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ],
    )
    recipe = {
        "source": {
            "config": {
                "object_filters": {
                    "include_objects": {
                        "Documents": ["ЗаказПокупателя"],
                    },
                },
            },
        },
    }

    class FakeClient:
        def list_objects(self, *, types):
            assert types == ["Documents"]
            return [
                SimpleNamespace(object_type="Documents", name="ЗаказПокупателя"),
            ]

        def get_tabular_parts(self, object_type, name):
            assert (object_type, name) == ("Documents", "ЗаказПокупателя")
            return [SimpleNamespace(name="Товары")]

        def get_integration_services(self, **_kwargs):
            return []

    result = module.validate_config_dump(
        recipe=recipe,
        path=xml_path,
        client=FakeClient(),
        check_scope=True,
    )

    assert not result.ok
    assert result.errors == [
        "Missing tabular section UUID in ConfigDumpInfo.xml: Documents.ЗаказПокупателя.Товары",
    ]


def test_validate_configdump_reports_selected_object_missing_from_api(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    xml_path = tmp_path / "ConfigDumpInfo.xml"
    _write_configdump(
        xml_path,
        [
            ("Document.ЗаказПокупателя", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ],
    )
    recipe = {
        "source": {
            "config": {
                "object_filters": {
                    "include_objects": {
                        "Documents": ["ЗаказПокупателя"],
                    },
                },
            },
        },
    }

    class FakeClient:
        def list_objects(self, *, types):
            assert types == ["Documents"]
            return []

        def get_integration_services(self, **_kwargs):
            return []

    result = module.validate_config_dump(
        recipe=recipe,
        path=xml_path,
        client=FakeClient(),
        check_scope=True,
    )

    assert not result.ok
    assert result.errors == [
        "1C API did not return selected object: Documents.ЗаказПокупателя",
    ]


def test_validate_configdump_reports_selected_tabular_section_missing_from_api(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    xml_path = tmp_path / "ConfigDumpInfo.xml"
    _write_configdump(
        xml_path,
        [
            ("Document.ЗаказПокупателя", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            (
                "Document.ЗаказПокупателя.TabularSection.Товары",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            ),
        ],
    )
    recipe = {
        "source": {
            "config": {
                "object_filters": {
                    "include_objects": {
                        "Documents": [
                            {
                                "name": "ЗаказПокупателя",
                                "tabular_sections": ["Товары"],
                            },
                        ],
                    },
                },
            },
        },
    }

    class FakeClient:
        def list_objects(self, *, types):
            assert types == ["Documents"]
            return [
                SimpleNamespace(object_type="Documents", name="ЗаказПокупателя"),
            ]

        def get_tabular_parts(self, object_type, name):
            assert (object_type, name) == ("Documents", "ЗаказПокупателя")
            return []

        def get_integration_services(self, **_kwargs):
            return []

    result = module.validate_config_dump(
        recipe=recipe,
        path=xml_path,
        client=FakeClient(),
        check_scope=True,
    )

    assert not result.ok
    assert result.errors == [
        "1C API did not return selected tabular section: Documents.ЗаказПокупателя.Товары",
    ]
