"""Golden checks for HA push carrier YAML generator (Binding P5c)."""
from __future__ import annotations

from integrations.ha_carrier_yaml import (
    build_carrier_yaml,
    ehal_base_unit,
    entity_placeholder,
)


def _minimal_house() -> dict:
    return {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "",
                "sens_pv_production_active": "",
                "set_grid_export_power_limit": "",
            }
        },
        "profiles": {},
    }


def _minimal_components() -> dict:
    return {
        "batteries": [
            {
                "id": "house",
                "type": "house",
                "ehal_bindings": {
                    "ess.house.sens_ess_soc": "",
                    "ess.house.set_ess_charge_power_limit": "",
                    "ess.house.set_ess_active_power": "",
                },
            }
        ]
    }


def _build(**kwargs) -> str:
    opts = {
        "earnie_host": "earnie-ha-lab",
        "earnie_port": 8541,
        "token": "TEST_TOKEN_12345678",
        "repeat_s": 10.0,
    }
    opts.update(kwargs)
    return build_carrier_yaml(_minimal_house(), _minimal_components(), **opts)


def test_carrier_yaml_contains_push_and_status():
    text = _build()
    assert "rest_command:" in text
    assert "grid.meter.sens_grid_power_active" in text
    assert "earnie_push_heartbeat" in text
    assert "/ehal/telemetry/heartbeat_smarthome/" in text
    assert "value_json.heartbeat_earnie" in text
    assert "/ehal/status.json?t=TEST_TOKEN_12345678" in text
    assert "sensor:" in text
    assert "platform: rest" in text


def test_carrier_yaml_periodic_time_pattern():
    text = _build(repeat_s=10.0)
    assert "trigger: time_pattern" in text
    assert 'seconds: "/10"' in text
    assert "automation:" in text


def test_carrier_yaml_entity_placeholders_only():
    text = _build()
    assert "ENTITY_grid_meter_sens_grid_power_active" in text
    assert "ENTITY_ess_house_sens_ess_soc" in text
    assert "ENTITY_ess_house_set_ess_charge_power_limit" in text
    # No pre-filled real entity_ids from bindings (values were empty).
    assert "sensor.real_" not in text
    assert entity_placeholder("grid.meter.sens_grid_power_active") == (
        "ENTITY_grid_meter_sens_grid_power_active"
    )


def test_carrier_yaml_unit_jinja_present():
    text = _build()
    assert "unit_of_measurement" in text
    assert "entity_unit" in text
    assert "ehal_value" in text
    assert "kilowatt" in text or "kw" in text
    assert "system_log.write" in text
    assert ehal_base_unit("grid.meter.sens_grid_power_active") == "W"
    assert ehal_base_unit("ess.house.sens_ess_soc") == "%"


def test_carrier_yaml_setpoint_automations():
    text = _build()
    assert "sensor.earnie_ehal_status" in text
    assert "number.set_value" in text
    assert "ess.house.set_ess_charge_power_limit" in text
    assert "json_attributes:" in text
    assert "hub_value" in text


def test_carrier_yaml_ha_ess_force_when_configured():
    house = _minimal_house()
    house["plant"]["ha_ess_force"] = {
        "driver": "huawei_solar",
        "device_id": "dev-luna-1",
        "duration_min": 20,
    }
    text = build_carrier_yaml(
        house,
        _minimal_components(),
        earnie_host="earnie-ha-lab",
        earnie_port=8541,
        token="TEST_TOKEN_12345678",
        repeat_s=10.0,
    )
    assert "huawei_solar.forcible_charge" in text
    assert "huawei_solar.forcible_discharge" in text
    assert "huawei_solar.stop_forcible_charge" in text
    assert "dev-luna-1" in text
    # Active power goes via force automation, not ENTITY number.set_value.
    assert "ENTITY_ess_house_set_ess_active_power" not in text
