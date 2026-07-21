"""Tests: charge_immediate_name bleibt in der normalisierten Config erhalten."""
from __future__ import annotations

import json

import config


def _minimal_charge_immediate_config() -> dict:
    return {
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
        "live_scenario_id": "live",
        "planning_horizon": {"mode": "sunrise_window"},
        "scenario_explorer_conf": {
            "path_cons_data": "runtime/cons_data_hourly.csv",
        },
        "flexible_consumers": [
            {
                "id": "eauto",
                "name": "E-Auto",
                "chart_color_index": 2,
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "daily_target_source": "config",
                "min_on_quarterhours": 4,
                "path_historical_log": "pfad/zum/eauto-log.csv",
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
                    "milp": {
                        "live_modus_a_min_remaining_kwh": 2.8,
                        "tie_break_on_epsilon": 0.001,
                        "tie_break_time_epsilon": 0.0001,
                    },
                },
            }
        ],
    }


def test_charge_immediate_name_loaded_from_json(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "tariffs.json").write_text(
        json.dumps(
            {
                "import_tariffs": [
                    {
                        "id": "fixed_imp",
                        "label": "Fix",
                        "type": "fixed_cent",
                        "fix_cent_kwh": 37.0,
                    }
                ],
                "export_tariffs": [
                    {"id": "fixed_exp", "label": "Fix", "type": "fixed", "k_push_cent": 3.5}
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "house_profiles.json").write_text(
        json.dumps({"profiles": []}),
        encoding="utf-8",
    )
    payload = _minimal_charge_immediate_config()
    live_settings = {
        "battery_id": "home",
        "pv_system_id": "roof",
        "import_tariff_id": "fixed_imp",
        "export_tariff_id": "fixed_exp",
        "house_profile_id": "",
    }
    components_doc = {
        "batteries": [
            {
                "id": "home",
                "label": "Home",
                "battery_capacity_kwh": 5.0,
                "battery_max_power_kw": 2.5,
                "battery_efficiency": 0.97,
                "battery_min_soc": 10.0,
                "battery_max_soc": 100.0,
                "threshold_power": 0.02,
                "battery_wear": {"enabled": False},
            }
        ],
        "pv_systems": [
            {"id": "roof", "label": "Roof", "kwp": 10.0, "pv_tilt": 25, "pv_azimuth": 0}
        ],
    }
    path = config_dir / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (config_dir / "components.json").write_text(json.dumps(components_doc), encoding="utf-8")
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {"id": "live", "label": "Live", "settings": live_settings},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(path))
    monkeypatch.setenv("ENERGY_OPTIMIZER_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_COMPONENTS_PATH",
        str(config_dir / "components.json"),
    )
    config.reinit_config()

    eauto = next(c for c in config.get_flexible_consumers() if c["id"] == "eauto")
    lox = (eauto.get("charging_schedule") or {}).get("loxone") or {}
    sched = eauto.get("charging_schedule") or {}
    assert lox.get("charge_immediate_name") == "E-Auto_SOFORT_LADEN"
    assert lox.get("charge_immediate_remaining_name") == "Ernie_Restzeit_Sofortladen"
    assert lox.get("battery_capacity_kwh_name") == "Batteriekapazität_E-Auto"
    assert "battery_capacity_kwh" not in sched
