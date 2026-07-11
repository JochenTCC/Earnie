"""Tests für konfigurierbare UI-Fragment-Refresh-Intervalle."""
from __future__ import annotations

import json

import pytest

import config
from ui import fragment_refresh


def _write_config(tmp_path, ui_block: dict | None) -> str:
    payload = {
        "system": {
            "global_timeout": 10,
            "loop_timeout": 900,
        },
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
            "battery_id": "",
            "pv_system_id": "",
            "house_profile_id": "",
            "import_tariff_id": "",
            "export_tariff_id": "",
        },
        "batteries": [],
        "pv_systems": [],
        "planning_horizon": {"mode": "sunset_window"},
        "file_paths_battery_simulation": {
            "path_cons_data": "runtime/cons_data_hourly.csv",
        },
        "flexible_consumers": [],
    }
    if ui_block is not None:
        payload["ui"] = ui_block
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_ui_fragment_defaults_without_ui_block(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_MAIN_SYNC_POLL_SEC", raising=False)
    path = _write_config(tmp_path, None)
    cfg = config.Config(config_path=path, require_loxone_credentials=False)
    assert cfg.get_ui_fragment_charts_sec() == 60
    assert cfg.get_ui_fragment_status_sec() == 10
    assert cfg.get_ui_main_sync_poll_sec() == 15


def test_ui_fragment_from_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC", raising=False)
    path = _write_config(
        tmp_path,
        {"fragment_refresh_charts_sec": 45, "fragment_refresh_status_sec": 5},
    )
    cfg = config.Config(config_path=path, require_loxone_credentials=False)
    assert cfg.get_ui_fragment_charts_sec() == 45
    assert cfg.get_ui_fragment_status_sec() == 5


def test_env_overrides_config(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", "90")
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC", "15")
    assert fragment_refresh.charts_fragment_interval_sec() == 90
    assert fragment_refresh.status_fragment_interval_sec() == 15


def test_main_sync_poll_env_override(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_MAIN_SYNC_POLL_SEC", "20")
    assert fragment_refresh.main_sync_poll_interval_sec() == 20


def test_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", "0")
    with pytest.raises(ValueError, match="mindestens 1"):
        fragment_refresh.charts_fragment_interval_sec()
