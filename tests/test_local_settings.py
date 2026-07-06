"""Tests für runtime/local_settings.json (maschinenspezifische Einstellungen)."""
from __future__ import annotations

import json

import pytest

import config


def _write_minimal_config(tmp_path, system_extra: dict | None = None) -> str:
    system = {
        "global_timeout": 10,
        "loop_timeout": 900,
        "event_trigger_enabled": True,
        "event_triggers": [],
    }
    if system_extra:
        system.update(system_extra)
    payload = {
        "awattar": {
            "url": "https://example.test",
            "fix_aufschlag_cent": 1.0,
            "netzverlust_faktor": 1.0,
            "mwst_austria_faktor": 1.0,
        },
        "system": system,
        "loxone_blocks": {
            "soc_name": "soc",
            "pv_counter_name": "pv",
            "log_filename": "log.csv",
            "pv_tuning_log_file": "pv.csv",
            "pv_power_name": "pv_act",
            "battery_power_name": "bat",
            "grid_power_name": "grid",
            "target_soc_name": "t_soc",
            "target_charge_power_name": "t_charge",
            "target_discharge_power_name": "t_discharge",
            "control_cmd_name": "cmd",
        },
        "runtime_settings": {
            "k_push_cent": 1.0,
            "pv_tilt": 18,
            "pv_azimuth": 0,
            "pv_kwp": 6.0,
            "battery_max_power_kw": 2.5,
            "battery_efficiency": 0.95,
            "battery_capacity_kwh": 5.0,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "threshold_power": 0.2,
            "latitude": 47.0,
            "longitude": 9.0,
            "timezone_name": "Europe/Vienna",
        },
        "planning_horizon": {"mode": "sunset_window"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_loxone_silent_mode_defaults_false_without_local_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path = _write_minimal_config(tmp_path)
    local_path = tmp_path / "missing_local_settings.json"
    cfg = config.Config(
        config_path=config_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    assert cfg.is_loxone_silent_mode() is False


def test_loxone_silent_mode_from_local_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path = _write_minimal_config(tmp_path)
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(json.dumps({"loxone_silent_mode": True}), encoding="utf-8")
    cfg = config.Config(
        config_path=config_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    assert cfg.is_loxone_silent_mode() is True


def test_rejects_loxone_silent_mode_in_central_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path = _write_minimal_config(tmp_path, {"loxone_silent_mode": True})
    local_path = tmp_path / "local_settings.json"
    with pytest.raises(ValueError, match="gehört nicht mehr in config.json"):
        config.Config(
            config_path=config_path,
            local_settings_path=str(local_path),
            require_loxone_credentials=False,
        )


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
