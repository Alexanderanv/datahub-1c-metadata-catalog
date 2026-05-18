from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_script_module():
    script_path = Path(__file__).parents[2] / "scripts" / "reference_ingest.py"
    spec = importlib.util.spec_from_file_location("reference_ingest", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reference_ingest_dry_run_uses_declared_order(tmp_path: Path, capsys) -> None:
    module = _load_script_module()
    recipe_path = tmp_path / "onec.dhub.yaml"
    db_recipe_path = tmp_path / "db.dhub.yaml"
    recipe_path.write_text(
        """
source:
  type: 1c-enterprise
  config:
    ingestion:
      emit_custom_aspects: false
""",
        encoding="utf-8",
    )
    db_recipe_path.write_text("source: {type: postgres, config: {}}\n", encoding="utf-8")

    args = SimpleNamespace(
        onec_recipe=str(recipe_path),
        db_recipe=str(db_recipe_path),
        datahub_command="datahub",
        skip_configdump_check=False,
        validate_configdump_scope="false",
        skip_custom_models_check=False,
        postgres_ingest_enabled="true",
        skip_db_pattern=False,
        dry_run=True,
    )

    assert module.run(args, env={}) == 0

    output = capsys.readouterr().out
    assert "validate ConfigDumpInfo.xml" in output
    assert "check DataHub custom model" not in output
    assert "run 1C ingestion" in output
    assert "build database table allow-list from /db-mapping" in output
    assert "run database ingestion" in output


def test_reference_ingest_can_disable_database_step(tmp_path: Path, capsys) -> None:
    module = _load_script_module()
    recipe_path = tmp_path / "onec.dhub.yaml"
    recipe_path.write_text(
        """
source:
  type: 1c-enterprise
  config:
    ingestion:
      emit_custom_aspects: false
""",
        encoding="utf-8",
    )

    args = SimpleNamespace(
        onec_recipe=str(recipe_path),
        db_recipe=str(tmp_path / "db.dhub.yaml"),
        datahub_command="datahub",
        skip_configdump_check=True,
        validate_configdump_scope="false",
        skip_custom_models_check=True,
        postgres_ingest_enabled="false",
        skip_db_pattern=False,
        dry_run=True,
    )

    assert module.run(args, env={}) == 0

    output = capsys.readouterr().out
    assert "run 1C ingestion" in output
    assert "Database ingestion is disabled" in output
    assert "run database ingestion" not in output


def test_reference_ingest_injects_generated_db_pattern(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    recipe_path = tmp_path / "onec.dhub.yaml"
    db_recipe_path = tmp_path / "db.dhub.yaml"
    recipe_path.write_text(
        """
source:
  type: 1c-enterprise
  config:
    ingestion:
      emit_custom_aspects: false
""",
        encoding="utf-8",
    )
    db_recipe_path.write_text("source: {type: postgres, config: {}}\n", encoding="utf-8")
    run_calls = []

    def fake_run_command(*, label, command, env, dry_run):
        run_calls.append((label, command, dict(env), dry_run))
        return 0

    def fake_capture_command(*, label, command, env, dry_run):
        assert label == "build database table allow-list from /db-mapping"
        assert not dry_run
        return r"1c\-test\.public\._document164\Z"

    monkeypatch.setattr(module, "_run_command", fake_run_command)
    monkeypatch.setattr(module, "_capture_command", fake_capture_command)

    args = SimpleNamespace(
        onec_recipe=str(recipe_path),
        db_recipe=str(db_recipe_path),
        datahub_command="datahub",
        skip_configdump_check=True,
        validate_configdump_scope="false",
        skip_custom_models_check=True,
        postgres_ingest_enabled="true",
        skip_db_pattern=False,
        dry_run=False,
    )

    assert module.run(args, env={}) == 0

    assert run_calls[-1][0] == "run database ingestion"
    assert run_calls[-1][2]["POSTGRES_TABLE_PATTERN_ALLOW"] == (
        r"1c\-test\.public\._document164\Z"
    )
