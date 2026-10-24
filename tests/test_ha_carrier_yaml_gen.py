"""Golden checks for HA push carrier YAML generator (Binding P5c)."""
from __future__ import annotations

import pytest

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
    assert ".set_value" in text
    assert "ess.house.set_ess_charge_power_limit" in text
    assert "json_attributes:" in text
    assert "hub_value" in text


def test_carrier_yaml_push_skips_non_numeric_state():
    # HA testbed F7: ``unavailable`` must hit the "push skipped" log, not ``| float``.
    text = _build()
    assert "{% if not (raw_state | is_number) %}{{ none }}{% elif u in [" in text
    assert "{% if u in ['w'" not in text


def test_carrier_yaml_status_sensor_has_no_json_attributes_path():
    # HA's jsonpath("$") returns False for a dict -> sensor without attributes,
    # so no setpoint automation would ever fire (HA testbed finding F13).
    text = _build()
    assert "json_attributes_path" not in text


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


def _setpoint_block(text: str) -> str:
    start = text.index("id: earnie_setpoint_ess_house_set_ess_charge_power_limit")
    nxt = text.find("\n  - id:", start)
    return text[start : nxt if nxt != -1 else len(text)]


def test_carrier_yaml_setpoints_are_reasserted_on_start_and_periodically():
    # HA testbed F8/F18: an attribute-change trigger alone never corrects a target
    # after an HA restart or a manual change while the published value is unchanged.
    block = _setpoint_block(_build(repeat_s=10.0))
    assert "trigger: homeassistant" in block
    assert "event: start" in block
    assert "trigger: time_pattern" in block
    assert 'seconds: "/10"' in block
    assert "attribute: ess.house.set_ess_charge_power_limit" in block


def test_carrier_yaml_setpoints_write_only_on_drift_and_ignore_unpublished():
    block = _setpoint_block(_build())
    assert "| float(none)" in block and "| abs >" in block
    # Unpublished field (automatic mode) is not an error and not a warning.
    assert "stop: Earnie published no value for this field" in block or (
        'stop: "Earnie published no value for this field"' in block
    )
    assert block.index("published no value") < block.index(".set_value")


def test_carrier_yaml_reports_unapplied_setpoints_to_earnie():
    # HA testbed F22: a refusing target must not abort the script with nested ERROR
    # lines and Earnie must learn that the value was not applied.
    text = _build()
    assert "earnie_push_hub_write_failed:" in text
    assert "/ehal/telemetry/hub_write_failed/1" in text
    block = _setpoint_block(text)
    assert "continue_on_error: true" in block
    assert "delay:" in block and "seconds: 5" in block
    assert "rest_command.earnie_push_hub_write_failed" in block
    # the failure push is only reachable after the delay (verification of the write)
    assert block.index("delay:") < block.index("rest_command.earnie_push_hub_write_failed")


def test_carrier_yaml_push_skip_message_names_the_unavailable_state():
    # HA testbed F24: an unavailable entity has a fine unit; the old text blamed the unit.
    text = _build()
    assert "is unavailable/non-numeric" in text


def test_carrier_yaml_setpoint_skip_message_only_for_converted_units(monkeypatch):
    # Bench L13: the unit text was logged for a non-numeric published value. The target
    # unit is only read for converted units (W/kWh/%/A); for those the skip message is
    # the unit one. Without a unit a non-numeric value is stopped before (no dead guard).
    text = _build()
    assert "setpoint skipped for ess.house.set_ess_charge_power_limit: unknown or incompatible" in text
    assert "unit_of_measurement on ENTITY_ess_house_set_ess_charge_power_limit (need W)" in text
    assert "{{ hub_value is none }}" in text

    monkeypatch.setattr("integrations.ha_carrier_yaml.ehal_base_unit", lambda _id: None)
    text = _build()
    assert "setpoint skipped" not in text
    assert "published value is not numeric" not in text
    assert "{{ hub_value is none }}" not in text
    assert ".set_value" in text


@pytest.mark.parametrize(
    "target,expected",
    [
        ("number.battery_charge_limit", "number.set_value"),
        ("input_number.battery_charge_limit", "input_number.set_value"),
    ],
)
def test_set_value_action_follows_the_entity_domain(target, expected):
    """Issue #60: ``input_number`` targets need ``input_number.set_value``."""
    from jinja2 import Template

    from integrations.ha_carrier_yaml import entity_placeholder, set_value_action

    placeholder = entity_placeholder("ess.house.set_ess_charge_power_limit")
    rendered_template = set_value_action(placeholder).replace(placeholder, target)
    assert Template(rendered_template).render() == expected


def test_carrier_yaml_uses_the_templated_set_value_action():
    text = _build()
    placeholder = "ENTITY_ess_house_set_ess_charge_power_limit"
    assert f"{{{{ '{placeholder}'.split('.')[0] }}}}.set_value" in text
    assert "action: number.set_value" not in text
