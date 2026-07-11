# tests/test_bootstrap_runtime.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_store import bootstrap


def test_bootstrap_creates_missing_files_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.example.json").write_text(
        json.dumps({"system": {"global_timeout": 10, "loop_timeout": 900}}),
        encoding="utf-8",
    )
    (config_dir / "config.minimal.json").write_text(
        json.dumps(
            {
                "batteries": [],
                "pv_systems": [],
                "flexible_consumers": [],
            }
        ),
        encoding="utf-8",
    )

    bootstrap.run()

    config_path = tmp_path / "config" / "config.json"
    cons_data_path = tmp_path / "runtime" / "cons_data_hourly.csv"
    assert config_path.is_file()
    assert cons_data_path.is_file()
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert config_payload["batteries"] == []

    original_cons_data = "timestamp;total_kw;baseload_kw;pv_kw;source\n2020-01-01 00:00:00;1;1;0;measured\n"
    cons_data_path.write_text(original_cons_data, encoding="utf-8")

    bootstrap.run()

    assert cons_data_path.read_text(encoding="utf-8") == original_cons_data


def test_bootstrap_copies_config_templates_from_image_bundle(tmp_path, monkeypatch):
    """NAS-Szenario: ./config-Volume enthält nur config.json, Vorlagen liegen im Image."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))

    share_dir = tmp_path / "share" / "config"
    share_dir.mkdir(parents=True)
    example_payload = {"system": {"event_triggers": []}, "market_prices": {}}
    schema_payload = {"title": "schema"}
    deviation_example_payload = {"version": 1, "rules": []}
    deviation_schema_payload = {"title": "deviation-schema"}
    (share_dir / "config.example.json").write_text(
        json.dumps(example_payload),
        encoding="utf-8",
    )
    (share_dir / "config.schema.json").write_text(
        json.dumps(schema_payload),
        encoding="utf-8",
    )
    (share_dir / "deviation_rules.example.json").write_text(
        json.dumps(deviation_example_payload),
        encoding="utf-8",
    )
    (share_dir / "deviation_rules.schema.json").write_text(
        json.dumps(deviation_schema_payload),
        encoding="utf-8",
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text("{}", encoding="utf-8")

    bootstrap.run()

    example_path = config_dir / "config.example.json"
    schema_path = config_dir / "config.schema.json"
    deviation_example_path = config_dir / "deviation_rules.example.json"
    deviation_schema_path = config_dir / "deviation_rules.schema.json"
    deviation_rules_path = config_dir / "deviation_rules.json"
    assert example_path.is_file()
    assert schema_path.is_file()
    assert deviation_example_path.is_file()
    assert deviation_schema_path.is_file()
    assert deviation_rules_path.is_file()
    assert json.loads(example_path.read_text(encoding="utf-8"))["system"]["event_triggers"] == []
    assert json.loads(schema_path.read_text(encoding="utf-8"))["title"] == "schema"
    assert json.loads(deviation_example_path.read_text(encoding="utf-8"))["version"] == 1
    assert json.loads(deviation_rules_path.read_text(encoding="utf-8"))["version"] == 1


def test_bootstrap_rejects_directory_instead_of_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.example.json").write_text("{}", encoding="utf-8")
    (config_dir / "config.json").mkdir()

    with pytest.raises(bootstrap.BootstrapError, match="Verzeichnis"):
        bootstrap.run()


def test_bootstrap_creates_dotenv_from_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))

    share_dir = tmp_path / "share" / "config"
    share_dir.mkdir(parents=True)
    (share_dir / ".env.example").write_text(
        "LOXONE_USER=test\nLOXONE_PASS=secret\nLOXONE_IP=10.0.0.1\n",
        encoding="utf-8",
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.example.json").write_text("{}", encoding="utf-8")
    (config_dir / "config.minimal.json").write_text("{}", encoding="utf-8")

    bootstrap.run()

    dotenv_path = config_dir / ".env"
    assert dotenv_path.is_file()
    content = dotenv_path.read_text(encoding="utf-8")
    assert "LOXONE_USER=test" in content


def test_bootstrap_migrates_legacy_root_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.example.json").write_text("{}", encoding="utf-8")
    (config_dir / "config.minimal.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text("LOXONE_USER=legacy\n", encoding="utf-8")

    bootstrap.run()

    assert (config_dir / ".env").read_text(encoding="utf-8") == "LOXONE_USER=legacy\n"
