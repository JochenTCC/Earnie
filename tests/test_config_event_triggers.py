"""Tests für system.event_triggers in config.py."""
from __future__ import annotations

import json

import pytest

import config


def _write_config(tmp_path, system_block: dict) -> str:
    payload = {
        "system": {
            "global_timeout": 10,
            "loop_timeout": 900,
            **system_block,
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
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_event_triggers_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    path = _write_config(
        tmp_path,
        {
            "event_triggers": [
                {
                    "id": "eauto_plugged_in",
                    "loxone_name": "Ernie_EAuto_Da",
                    "signal_type": "binary",
                    "on_change": "rising",
                    "label": "E-Auto angeschlossen",
                }
            ]
        },
    )
    cfg = config.Config(config_path=path, require_loxone_credentials=False)
    triggers = cfg.get_event_triggers()
    assert len(triggers) == 1
    assert triggers[0]["id"] == "eauto_plugged_in"
    assert triggers[0]["on_change"] == "rising"


def test_duplicate_trigger_id_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    path = _write_config(
        tmp_path,
        {
            "event_triggers": [
                {
                    "id": "dup",
                    "loxone_name": "A",
                    "signal_type": "binary",
                    "on_change": "any",
                },
                {
                    "id": "dup",
                    "loxone_name": "B",
                    "signal_type": "binary",
                    "on_change": "any",
                },
            ]
        },
    )
    with pytest.raises(ValueError, match="doppelte id"):
        config.Config(config_path=path, require_loxone_credentials=False)


def test_text_trigger_invalid_on_change_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    path = _write_config(
        tmp_path,
        {
            "event_triggers": [
                {
                    "id": "ready",
                    "loxone_name": "FertigUm",
                    "signal_type": "text",
                    "on_change": "rising",
                }
            ]
        },
    )
    with pytest.raises(ValueError, match="on_change"):
        config.Config(config_path=path, require_loxone_credentials=False)
