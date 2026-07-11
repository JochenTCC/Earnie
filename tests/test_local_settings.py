"""Tests für runtime/local_settings.json (maschinenspezifische Einstellungen)."""
from __future__ import annotations

import json

import config
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree


def _write_minimal_config(tmp_path, system_extra: dict | None = None) -> tuple[str, str]:
    system = {
        "global_timeout": 10,
        "loop_timeout": 900,
        "event_trigger_enabled": True,
        "event_triggers": [],
    }
    if system_extra:
        system.update(system_extra)
    return write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(extra={"system": system}),
    )


def test_loxone_silent_mode_defaults_true_without_local_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = _write_minimal_config(tmp_path)
    local_path = tmp_path / "missing_local_settings.json"
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    assert cfg.is_loxone_silent_mode() is True


def test_loxone_silent_mode_from_local_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = _write_minimal_config(tmp_path)
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(json.dumps({"loxone_silent_mode": True}), encoding="utf-8")
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    assert cfg.is_loxone_silent_mode() is True


def test_loxone_silent_mode_from_central_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = _write_minimal_config(tmp_path, {"loxone_silent_mode": True})
    local_path = tmp_path / "local_settings.json"
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    assert cfg.is_loxone_silent_mode() is True


def test_loxone_silent_mode_local_settings_overrides_central_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = _write_minimal_config(tmp_path, {"loxone_silent_mode": False})
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(json.dumps({"loxone_silent_mode": True}), encoding="utf-8")
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    assert cfg.is_loxone_silent_mode() is True


def test_bootstrap_creates_local_settings(tmp_path, monkeypatch):
    from runtime_store import bootstrap

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.example.json").write_text("{}", encoding="utf-8")
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    example = tmp_path / "runtime" / "local_settings.example.json"
    example.parent.mkdir(parents=True)
    example.write_text(json.dumps({"loxone_silent_mode": False}), encoding="utf-8")

    bootstrap.run()

    local_path = tmp_path / "runtime" / "local_settings.json"
    assert local_path.is_file()
    assert json.loads(local_path.read_text(encoding="utf-8"))["loxone_silent_mode"] is False
