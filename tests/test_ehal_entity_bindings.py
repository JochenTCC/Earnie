"""Tests for 2.4.k plant/consumer ehal_bindings migration."""
from __future__ import annotations

import pytest

from house_config.ehal_bindings import (
    ensure_migrated,
    migrate_consumer_legacy_to_ehal_bindings,
    migrate_loxone_blocks_to_plant,
    resolve_plant_binding,
    strip_migrated_config_keys,
)
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
    assert "pv_follow_name" not in bindings
    assert bindings["flex.ev1.sens_power_act"] == "EV_Power"
    assert bindings["flex.ev1.set_enable"] == "EV_Enable"


def test_migrate_consumer_flex_power_setpoint_dropped():
    consumer = {
        "id": "pump",
        "type": "generic",
        "loxone_inputs": {"power_name": "Pump_P"},
        "loxone_outputs": {"power_setpoint_name": "Pump_Set", "enable_name": "Pump_En"},
    }
    bindings = migrate_consumer_legacy_to_ehal_bindings(consumer)
    assert bindings["flex.pump.sens_power_act"] == "Pump_P"
    assert bindings["flex.pump.set_enable"] == "Pump_En"
    assert "flex.pump.set_power_setpoint" not in bindings
    assert "set_evcs_max_current" not in bindings


def test_migrate_strips_existing_flex_power_setpoint_binding():
    consumer = {
        "id": "pump",
        "type": "generic",
        "ehal_bindings": {
            "flex.pump.sens_power_act": "Pump_P",
            "flex.pump.set_enable": "Pump_En",
            "flex.pump.set_power_setpoint": "Pump_Set",
            "flex.power_setpoint_name": "Legacy_Stub",
        },
    }
    bindings = migrate_consumer_legacy_to_ehal_bindings(consumer)
    assert bindings["flex.pump.sens_power_act"] == "Pump_P"
    assert bindings["flex.pump.set_enable"] == "Pump_En"
    assert "flex.pump.set_power_setpoint" not in bindings
    assert "flex.power_setpoint_name" not in bindings


def test_resolve_plant_binding_ignores_ess_and_loxone_blocks():
    house = {"plant": {"ehal_bindings": {}}}
    config = {"loxone_blocks": {"soc_name": "Battery_SOC"}}
    assert resolve_plant_binding(house, "sens_ess_soc", config) == ""
    house2 = {"plant": {"ehal_bindings": {"sens_ess_soc": "Plant_SOC"}}}
    assert resolve_plant_binding(house2, "sens_ess_soc", config) == ""
    house3 = {"plant": {"ehal_bindings": {"sens_pv_production_active": "Plant_PV"}}}
    assert resolve_plant_binding(house3, "sens_pv_production_active", config) == "Plant_PV"


def test_ensure_migrated_refuses_loxone_blocks():
    house = {"plant": {"ehal_bindings": {"sens_pv_production_active": "PV"}}}
    config = {"loxone_blocks": {"soc_name": "Battery_SOC"}}
    with pytest.raises(ValueError, match="loxone_blocks"):
        ensure_migrated(house, config)


def test_ensure_migrated_refuses_plant_flat_ess_when_batteries_exist(
    tmp_path, monkeypatch
):
    import json

    from ehal.ess_fields import ess_field

    from tests.config_fixtures import main_hybrid_inverter

    components = {
        "inverters": [main_hybrid_inverter()],
        "batteries": [
            {
                "id": "house",
                "type": "house",
                "inverter_id": "wr_main",
                "regulates_on": "grid",
                "ehal_bindings": {ess_field("house", "sens_ess_soc"): ""},
            }
        ],
        "pv_systems": [],
    }
    path = tmp_path / "components.json"
    path.write_text(json.dumps(components), encoding="utf-8")
    monkeypatch.setattr(
        "runtime_store.persist_paths.resolve_components_json_path",
        lambda: str(path),
    )
    house = {"plant": {"ehal_bindings": {"sens_ess_soc": "Battery_SOC"}}}
    with pytest.raises(ValueError, match="retired flat sens_ess_soc|plant-flat ESS"):
        ensure_migrated(house, {})


def test_ensure_migrated_strips_triggers_keeps_bindings():
    house = {
        "plant": {
            "ehal_bindings": {"sens_pv_production_active": "PV"},
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
    assert new_house["plant"]["ehal_bindings"]["sens_pv_production_active"] == "PV"
    assert "event_triggers" not in new_house["plant"]
    assert "event_triggers" not in new_house["profiles"][0]["consumers"][0]
    stripped = strip_migrated_config_keys(new_config)
    assert "event_triggers" not in stripped.get("system", {})
    assert "event_trigger_enabled" not in stripped.get("system", {})


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
    assert "sens_temperature_outside" not in bindings
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
    assert "sens_temperature_outside" not in (cons.get("ehal_bindings") or {})
    assert out["plant"]["ehal_bindings"]["sens_temperature_outside"] == "Außen"


def test_ensure_migrated_strips_consumer_ambient_when_plant_already_set():
    house = {
        "plant": {
            "ehal_bindings": {"sens_temperature_outside": "PlantOutside"},
        },
        "profiles": [
            {
                "id": "p1",
                "consumers": [
                    {
                        "id": "swimspa",
                        "type": "thermal_rc",
                        "ehal_bindings": {
                            "sens_temperature_water": "Ist",
                            "sens_temperature_outside": "LeftoverOutside",
                        },
                    }
                ],
            }
        ],
    }
    out, _cfg, changed = ensure_migrated(house, {})
    assert changed
    cons = out["profiles"][0]["consumers"][0]
    assert "sens_temperature_outside" not in (cons.get("ehal_bindings") or {})
    assert out["plant"]["ehal_bindings"]["sens_temperature_outside"] == "PlantOutside"


def test_ensure_migrated_strips_consumer_energy_export():
    house = {
        "profiles": [
            {
                "id": "p1",
                "consumers": [
                    {
                        "id": "kochen",
                        "type": "generic",
                        "ehal_bindings": {
                            "sens_energy_total": "",
                            "sens_energy_export": "",
                        },
                    }
                ],
            }
        ],
    }
    out, _cfg, changed = ensure_migrated(house, {})
    assert changed
    cons = out["profiles"][0]["consumers"][0]
    bindings = cons.get("ehal_bindings") or {}
    assert "sens_energy_total" in bindings
    assert "sens_energy_export" not in bindings


def test_marker_get_filter_remaining_hours_prefers_ehal():
    from settings.ehal_marker_resolve import marker_get_filter_remaining_hours

    consumer = {
        "ehal_bindings": {"get_filter_remaining_hours": "Earnie_Pool_Filter_Sollstunden"},
        "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
    }
    assert marker_get_filter_remaining_hours(consumer) == "Earnie_Pool_Filter_Sollstunden"
    assert marker_get_filter_remaining_hours({"loxone_target_hours_name": "Legacy_Hours"}) == ""
