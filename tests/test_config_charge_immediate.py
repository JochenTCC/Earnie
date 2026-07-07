"""Tests: charge_immediate_name bleibt in der normalisierten Config erhalten."""
from __future__ import annotations

import json

import config


def _minimal_charge_immediate_config() -> dict:
    return {
        "awattar": {
            "url": "https://api.awattar.at/v1/marketdata",
            "fix_aufschlag_cent": 1.5,
            "netzverlust_faktor": 1.03,
            "mwst_austria_faktor": 1.2,
        },
        "eauto_milp": {
            "live_modus_a_min_remaining_kwh": 2.8,
            "tie_break_on_epsilon": 0.001,
            "tie_break_time_epsilon": 0.0001,
        },
        "battery_wear": {"enabled": False},
        "system": {"global_timeout": 10, "loop_timeout": 900},
        "loxone_blocks": {
            "soc_name": "Battery_SOC",
            "pv_counter_name": "PV_Counter",
            "log_filename": "Verbrauch.csv",
            "pv_tuning_log_file": "runtime/pv_accuracy_log.csv",
            "pv_power_name": "PV_Act",
            "battery_power_name": "Battery_Act",
            "grid_power_name": "Grid_Act",
            "target_soc_name": "Target_SoC",
            "target_charge_power_name": "Target_Charge",
            "target_discharge_power_name": "Target_Discharge",
            "control_cmd_name": "Control_Cmd",
        },
        "runtime_settings": {
            "k_push_cent": 3.5,
            "feed_in_mode": "fixed",
            "pv_tilt": 25,
            "pv_azimuth": 0,
            "pv_kwp": 10.0,
            "battery_max_power_kw": 2.5,
            "battery_efficiency": 0.97,
            "battery_capacity_kwh": 5.0,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "threshold_power": 0.02,
            "latitude": 48.0,
            "longitude": 10.0,
            "timezone_name": "Europe/Vienna",
        },
        "planning_horizon": {"mode": "sunset_window"},
        "flexible_consumers": [
            {
                "id": "eauto",
                "name": "E-Auto",
                "chart_color_index": 2,
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "daily_target_source": "config",
                "min_on_quarterhours": 4,
                "path_log": "pfad/zum/eauto-log.csv",
                "signal_type": "power",
                "optimizer_enabled": True,
                "charging_schedule": {
                    "enabled": True,
                    "forecast_when_absent": True,
                    "target_soc_percent": 100.0,
                    "charging_efficiency": 0.95,
                    "weekday": {
                        "car_available_from_hour": 18,
                        "ready_by_hour": 7,
                        "daily_rest_soc": 40.0,
                    },
                    "weekend": {
                        "car_available_from_hour": 20,
                        "ready_by_hour": 9,
                        "daily_rest_soc": 30.0,
                    },
                    "loxone": {
                        "plugged_in_name": "EAuto_Angeschlossen",
                        "ready_by_time_name": "EAuto_FertigUm",
                        "soc_at_plug_in_name": "EAuto_SOC_bei_Anschluss",
                        "charge_immediate_name": "E-Auto_SOFORT_LADEN",
                        "charge_immediate_remaining_name": "Ernie_Restzeit_Sofortladen",
                        "battery_capacity_kwh_name": "Batteriekapazität_E-Auto",
                        "nominal_power_kw_name": "EAuto_MaxLeistung",
                    },
                },
            }
        ],
    }


def test_charge_immediate_name_loaded_from_json(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_minimal_charge_immediate_config()), encoding="utf-8")
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(path))
    config.reinit_config()

    eauto = next(c for c in config.get_flexible_consumers() if c["id"] == "eauto")
    lox = (eauto.get("charging_schedule") or {}).get("loxone") or {}
    sched = eauto.get("charging_schedule") or {}
    assert lox.get("charge_immediate_name") == "E-Auto_SOFORT_LADEN"
    assert lox.get("charge_immediate_remaining_name") == "Ernie_Restzeit_Sofortladen"
    assert lox.get("battery_capacity_kwh_name") == "Batteriekapazität_E-Auto"
    assert "battery_capacity_kwh" not in sched
