"""Tests for 2.4.k plant/consumer ehal_bindings migration and trigger aggregation."""
from __future__ import annotations

from house_config.ehal_bindings import (
    aggregate_event_triggers,
    ensure_migrated,
    migrate_config_triggers_to_plant,
    migrate_consumer_legacy_to_ehal_bindings,
    migrate_loxone_blocks_to_plant,
    resolve_plant_binding,
    strip_migrated_config_keys,
)
from settings.config_loaders import load_loxone_block_params
from settings.ehal_marker_resolve import marker_sens_evcs_connected, marker_set_evcs_current
from settings.system_settings import load_event_triggers


def test_migrate_loxone_blocks_to_plant():
    bindings = migrate_loxone_blocks_to_plant(
        {
            "soc_name": "Battery_SOC",
            "grid_power_name": "Grid_P",
            "control_cmd_name": "Cmd",
            "log_filename": "log.csv",
            "pv_counter_name": "PV_kWh",
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
    assert bindings["sens_evcs_nominal_current"] == "EV_A"
    assert bindings["get_evcs_ready_by_time"] == "EV_Ready"
    assert bindings["charge_immediate_name"] == "EV_Now"
    assert bindings["set_evcs_current"] == "EV_SetA"
    assert bindings["pv_follow_name"] == "EV_PV"
    assert bindings["flex.power_name"] == "EV_Power"
    assert bindings["flex.enable_name"] == "EV_Enable"


def test_migrate_consumer_flex_power_setpoint():
    consumer = {
        "id": "pump",
        "type": "generic",
        "loxone_inputs": {"power_name": "Pump_P"},
        "loxone_outputs": {"power_setpoint_name": "Pump_Set", "enable_name": "Pump_En"},
    }
    bindings = migrate_consumer_legacy_to_ehal_bindings(consumer)
    assert bindings["flex.power_setpoint_name"] == "Pump_Set"
    assert "set_evcs_current" not in bindings


def test_migrate_config_triggers_to_plant_event_stub():
    triggers, bindings = migrate_config_triggers_to_plant(
        [
            {
                "id": "plug",
                "loxone_name": "Merker_A",
                "signal_type": "binary",
                "on_change": "rising",
                "label": "EV",
            }
        ],
        {"sens_grid_power_active": "Grid_P"},
    )
    assert triggers[0]["ehal_field"] == "event.plug"
    assert bindings["event.plug"] == "Merker_A"
    assert bindings["sens_grid_power_active"] == "Grid_P"


def test_migrate_config_triggers_reuses_existing_binding():
    triggers, bindings = migrate_config_triggers_to_plant(
        [
            {
                "id": "plug",
                "loxone_name": "EV_Da",
                "signal_type": "binary",
                "on_change": "rising",
                "label": "EV",
            }
        ],
        {"sens_evcs_connected": "EV_Da"},
    )
    assert triggers[0]["ehal_field"] == "sens_evcs_connected"
    assert "event.plug" not in bindings


def test_aggregate_resolves_loxone_name():
    house = {
        "plant": {
            "ehal_bindings": {"event.plug": "Merker_A"},
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
                        "ehal_bindings": {"sens_evcs_connected": "EV_Da"},
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
    specs = aggregate_event_triggers(house)
    assert len(specs) == 2
    by_id = {s["id"]: s for s in specs}
    assert by_id["plug"]["loxone_name"] == "Merker_A"
    assert by_id["ev_plug"]["loxone_name"] == "EV_Da"


def test_resolve_plant_binding_dual_read_blocks():
    house = {"plant": {"ehal_bindings": {}}}
    config = {"loxone_blocks": {"soc_name": "Battery_SOC"}}
    assert resolve_plant_binding(house, "sens_ess_soc", config) == "Battery_SOC"
    house2 = {"plant": {"ehal_bindings": {"sens_ess_soc": "Plant_SOC"}}}
    assert resolve_plant_binding(house2, "sens_ess_soc", config) == "Plant_SOC"


def test_ensure_migrated_and_strip_triggers():
    house = {"profiles": [{"id": "live", "consumers": []}]}
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
            ]
        },
    }
    new_house, new_config, changed = ensure_migrated(house, config)
    assert changed is True
    assert new_house["plant"]["ehal_bindings"]["sens_ess_soc"] == "Battery_SOC"
    assert new_house["plant"]["event_triggers"][0]["id"] == "plug"
    stripped = strip_migrated_config_keys(new_config)
    assert stripped["system"]["event_triggers"] == []
    assert "soc_name" not in stripped["loxone_blocks"]
    assert "grid_power_name" not in stripped["loxone_blocks"]
    assert stripped["loxone_blocks"]["log_filename"] == "Verbrauch.csv"


def test_load_event_triggers_migrates_from_config():
    config = {
        "system": {
            "event_triggers": [
                {
                    "id": "plug",
                    "loxone_name": "Merker_A",
                    "signal_type": "binary",
                    "on_change": "rising",
                    "label": "EV",
                }
            ]
        }
    }
    triggers = load_event_triggers(config, house_doc={})
    assert len(triggers) == 1
    assert triggers[0]["loxone_name"] == "Merker_A"


def test_load_loxone_block_params_prefers_plant_bindings(tmp_path):
    config = {
        "loxone_blocks": {
            "soc_name": "Old_SOC",
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
    assert params["LOXONE_LOG_FILENAME"] == "log.csv"


def test_load_loxone_block_params_no_dual_read_when_plant_set(tmp_path):
    config = {
        "loxone_blocks": {
            "soc_name": "Old_SOC",
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
            "set_evcs_current": "Bind_A",
        },
        "charging_schedule": {"loxone": {"plugged_in_name": "Legacy_Da"}},
        "loxone_outputs": {"power_setpoint_name": "Legacy_A"},
    }
    assert marker_sens_evcs_connected(consumer) == "Bind_Da"
    assert marker_set_evcs_current(consumer) == "Bind_A"
