"""Tests for 2.4.k plant/consumer ehal_bindings migration."""
from __future__ import annotations

from house_config.ehal_bindings import (
    ensure_migrated,
    migrate_consumer_legacy_to_ehal_bindings,
    migrate_loxone_blocks_to_plant,
    resolve_plant_binding,
    strip_migrated_config_keys,
)
from settings.config_loaders import load_loxone_block_params
from settings.ehal_marker_resolve import marker_sens_evcs_connected, marker_set_evcs_max_current


def test_migrate_loxone_blocks_to_plant():
    bindings = migrate_loxone_blocks_to_plant(
        {
            "soc_name": "Battery_SOC",
            "grid_power_name": "Grid_P",
            "control_cmd_name": "Cmd",
            "log_filename": "log.csv",
        }
    )
    assert bindings["sens_ess_soc"] == "Battery_SOC"
    assert bindings["sens_grid_power_active"] == "Grid_P"
    assert bindings["set_ess_mode"] == "Cmd"
    assert "log_filename" not in bindings
    assert "pv_counter_name" not in bindings


def test_migrate_consumer_legacy_to_ehal_bindings_ev():
    consumer = {
        "id": "ev1",
        "type": "ev",
        "charging_schedule": {
            "loxone": {
                "plugged_in_name": "EV_Da",
                "actual_soc_name": "EV_SOC",
                "battery_capacity_kwh_name": "EV_Cap",
                "nominal_power_kw_name": "EV_A",
                "ready_by_time_name": "EV_Ready",
                "charge_immediate_name": "EV_Now",
            }
        },
        "loxone_inputs": {"power_name": "EV_Power"},
        "loxone_outputs": {
            "power_setpoint_name": "EV_SetA",
            "pv_follow_name": "EV_PV",
            "enable_name": "EV_Enable",
        },
    }
    bindings = migrate_consumer_legacy_to_ehal_bindings(consumer)
    assert bindings["sens_evcs_connected"] == "EV_Da"
    assert bindings["sens_evcs_soc_act"] == "EV_SOC"
    assert bindings["sens_evcs_bat_capacity"] == "EV_Cap"
    assert bindings["get_evcs_nominal_current"] == "EV_A"
    assert bindings["get_evcs_ready_by_time"] == "EV_Ready"
    assert bindings["charge_immediate_name"] == "EV_Now"
    assert bindings["set_evcs_max_current"] == "EV_SetA"
    assert bindings["pv_follow_name"] == "EV_PV"
    assert bindings["flex.ev1.sens_power_act"] == "EV_Power"
    assert bindings["flex.ev1.set_enable"] == "EV_Enable"


def test_migrate_consumer_flex_power_setpoint():
    consumer = {
        "id": "pump",
        "type": "generic",
        "loxone_inputs": {"power_name": "Pump_P"},
        "loxone_outputs": {"power_setpoint_name": "Pump_Set", "enable_name": "Pump_En"},
    }
    bindings = migrate_consumer_legacy_to_ehal_bindings(consumer)
    assert bindings["flex.pump.set_power_setpoint"] == "Pump_Set"
    assert "set_evcs_max_current" not in bindings


def test_resolve_plant_binding_dual_read_blocks():
    house = {"plant": {"ehal_bindings": {}}}
    config = {"loxone_blocks": {"soc_name": "Battery_SOC"}}
    assert resolve_plant_binding(house, "sens_ess_soc", config) == "Battery_SOC"
    house2 = {"plant": {"ehal_bindings": {"sens_ess_soc": "Plant_SOC"}}}
    assert resolve_plant_binding(house2, "sens_ess_soc", config) == "Plant_SOC"


def test_ensure_migrated_strips_triggers_keeps_bindings():
    house = {
        "plant": {
            "ehal_bindings": {},
            "event_triggers": [
                {
                    "id": "plug",
                    "ehal_field": "event.plug",
                    "signal_type": "binary",
                    "on_change": "rising",
                    "label": "EV",
                }
            ],
        },
        "profiles": [
            {
                "id": "live",
                "consumers": [
                    {
                        "id": "ev1",
                        "event_triggers": [
                            {
                                "id": "ev_plug",
                                "ehal_field": "sens_evcs_connected",
                                "signal_type": "binary",
                                "on_change": "any",
                                "label": "car",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    config = {
        "loxone_blocks": {
            "soc_name": "Battery_SOC",
            "grid_power_name": "Grid_P",
            "log_filename": "Verbrauch.csv",
        },
        "system": {
            "event_triggers": [
                {
                    "id": "plug",
                    "loxone_name": "Merker_A",
                    "signal_type": "binary",
                    "on_change": "rising",
                    "label": "EV",
                }
            ],
            "event_trigger_enabled": True,
            "event_poll_interval_sec": 60,
        },
    }
    new_house, new_config, changed = ensure_migrated(house, config)
    assert changed is True
    assert new_house["plant"]["ehal_bindings"]["sens_ess_soc"] == "Battery_SOC"
    assert "event_triggers" not in new_house["plant"]
    assert "event_triggers" not in new_house["profiles"][0]["consumers"][0]
    stripped = strip_migrated_config_keys(new_config)
    assert "event_triggers" not in stripped.get("system", {})
    assert "event_trigger_enabled" not in stripped.get("system", {})
    assert "loxone_blocks" not in stripped


def test_load_loxone_block_params_prefers_plant_bindings(tmp_path):
    config = {
        "loxone_blocks": {
            "soc_name": "Old_SOC",
            "pv_power_name": "pv_act",
            "battery_power_name": "bat",
            "grid_power_name": "grid",
            "target_charge_power_name": "t_charge",
            "target_discharge_power_name": "t_discharge",
            "control_cmd_name": "cmd",
        }
    }
    house = {
        "plant": {
            "ehal_bindings": {
                "sens_ess_soc": "New_SOC",
                "sens_grid_power_active": "Plant_Grid",
                "sens_pv_production_active": "Plant_PV",
                "sens_ess_power": "Plant_Bat",
                "set_ess_charge_power_limit": "Plant_Ch",
                "set_ess_discharge_power_limit": "Plant_Dis",
                "set_ess_mode": "Plant_Cmd",
            }
        }
    }
    params = load_loxone_block_params(config, str(tmp_path / "config.json"), house_doc=house)
    assert params["LOXONE_SOC_NAME"] == "New_SOC"
    assert params["LOXONE_GRID_POWER_NAME"] == "Plant_Grid"
    assert "LOXONE_LOG_FILENAME" not in params
    assert "PV_TUNING_LOG_FILE" not in params


def test_load_loxone_block_params_without_removed_extras(tmp_path):
    """pv_counter_name / target_soc_name / FTP / PV-tuning are removed from the loader surface."""
    config = {"loxone_blocks": {}}
    house = {
        "plant": {
            "ehal_bindings": {
                "sens_ess_soc": "SOC",
                "sens_grid_power_active": "Grid",
                "sens_pv_production_active": "PV",
                "sens_ess_power": "Bat",
                "set_ess_charge_power_limit": "Ch",
                "set_ess_discharge_power_limit": "Dis",
                "set_ess_mode": "Cmd",
            }
        }
    }
    params = load_loxone_block_params(config, str(tmp_path / "config.json"), house_doc=house)
    assert "LOXONE_PV_COUNTER_NAME" not in params
    assert "LOXONE_TARGET_SOC_NAME" not in params
    assert "LOXONE_LOG_FILENAME" not in params
    assert "PV_TUNING_LOG_FILE" not in params
    assert params["LOXONE_SOC_NAME"] == "SOC"


def test_load_loxone_block_params_no_dual_read_when_plant_set(tmp_path):
    config = {
        "loxone_blocks": {
            "soc_name": "Old_SOC",
            "pv_power_name": "pv_act",
            "battery_power_name": "bat",
            "grid_power_name": "grid",
            "target_charge_power_name": "t_charge",
            "target_discharge_power_name": "t_discharge",
            "control_cmd_name": "cmd",
        }
    }
    house = {"plant": {"ehal_bindings": {"sens_ess_soc": "New_SOC"}}}
    params = load_loxone_block_params(config, str(tmp_path / "config.json"), house_doc=house)
    assert params["LOXONE_SOC_NAME"] == "New_SOC"
    assert params["LOXONE_GRID_POWER_NAME"] == ""


def test_ehal_marker_resolve_prefers_bindings():
    consumer = {
        "ehal_bindings": {
            "sens_evcs_connected": "Bind_Da",
            "set_evcs_max_current": "Bind_A",
        },
        "charging_schedule": {"loxone": {"plugged_in_name": "Legacy_Da"}},
        "loxone_outputs": {"power_setpoint_name": "Legacy_A"},
    }
    assert marker_sens_evcs_connected(consumer) == "Bind_Da"
    assert marker_set_evcs_max_current(consumer) == "Bind_A"


def test_migrate_consumer_legacy_thermal_to_ehal_bindings():
    consumer = {
        "id": "swimspa",
        "type": "thermal_rc",
        "loxone_inputs": {"power_name": "Spa_P"},
        "loxone_outputs": {"enable_name": "Spa_En"},
        "thermal_control": {
            "loxone": {
                "actual_temp_name": "Spa_Ist",
                "setpoint_temp_name": "Spa_Soll",
                "ambient_temp_name": "Outside",
                "tolerance_c_name": "Spa_Tol",
                "heating_active_name": "Spa_Heat",
            }
        },
    }
    bindings = migrate_consumer_legacy_to_ehal_bindings(consumer)
    assert bindings["sens_temperature_water"] == "Spa_Ist"
    assert bindings["get_temperature_water_setpoint"] == "Spa_Soll"
    assert bindings["sens_temperature_outside"] == "Outside"
    assert bindings["get_temperature_tolerance_c"] == "Spa_Tol"
    assert bindings["sens_heating_active"] == "Spa_Heat"
    assert bindings["flex.swimspa.sens_power_act"] == "Spa_P"
    assert bindings["flex.swimspa.set_enable"] == "Spa_En"


def test_ensure_migrated_strips_thermal_loxone_and_promotes_ambient():
    house = {
        "plant": {"ehal_bindings": {}},
        "profiles": [
            {
                "id": "p1",
                "consumers": [
                    {
                        "id": "swimspa",
                        "type": "thermal_rc",
                        "thermal_control": {
                            "enabled": True,
                            "setpoint_c": 35.0,
                            "loxone": {
                                "actual_temp_name": "Ist",
                                "ambient_temp_name": "Außen",
                            },
                        },
                        "loxone_outputs": {"enable_name": "En"},
                    }
                ],
            }
        ],
    }
    out, _cfg, changed = ensure_migrated(house, {})
    assert changed
    cons = out["profiles"][0]["consumers"][0]
    assert "loxone" not in (cons.get("thermal_control") or {})
    assert cons["thermal_control"]["setpoint_c"] == 35.0
    assert "loxone_outputs" not in cons
    assert cons["ehal_bindings"]["sens_temperature_water"] == "Ist"
    assert out["plant"]["ehal_bindings"]["sens_temperature_outside"] == "Außen"


def test_marker_get_filter_remaining_hours_prefers_ehal():
    from settings.ehal_marker_resolve import marker_get_filter_remaining_hours

    consumer = {
        "ehal_bindings": {"get_filter_remaining_hours": "Earnie_Pool_Filter_Sollstunden"},
        "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
    }
    assert marker_get_filter_remaining_hours(consumer) == "Earnie_Pool_Filter_Sollstunden"
    assert marker_get_filter_remaining_hours({"loxone_target_hours_name": "Legacy_Hours"}) == ""
