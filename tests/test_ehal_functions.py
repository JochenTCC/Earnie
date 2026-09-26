"""EHAL functions: available only when all required fields are mapped."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ehal.functions import (
    available_functions,
    function_statuses,
    incomplete_function_messages,
)
from house_sim.archetype import load_archetype
from house_sim.mock_rest import DEFAULT_BENCH_TOKEN, start_mock_rest, stop_mock_rest
from integrations.ehal_live import SKIPPED_MESSAGE, build_ehal_write_records
from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.ha_meter_energy import read_plant_energy_readings
from integrations.loxone_adapter import LoxoneAdapter, LoxoneConfig

TELEMETRY = {
    "sens_grid_power_active": "sensor.grid",
    "sens_pv_production_active": "sensor.pv",
    "sens_ess_soc": "sensor.soc",
}
LIMITS = {
    "set_ess_charge_power_limit": "number.charge",
    "set_ess_discharge_power_limit": "number.discharge",
}
SETPOINT_TS = {"schema_version": 3, "ts": "2026-01-01T00:00:00Z", "adapter_id": "earnie-hems"}


def _state(statuses, function_id):
    return next(s for s in statuses if s.function.id == function_id)


def test_states_available_incomplete_not_configured():
    statuses = function_statuses({**TELEMETRY, "set_ess_charge_power_limit": "number.charge"})
    assert _state(statuses, "telemetry").state == "available"
    limits = _state(statuses, "ess_limits")
    assert limits.state == "incomplete"
    assert limits.missing == ("set_ess_discharge_power_limit",)
    assert _state(statuses, "ess_active").state == "not_configured"
    assert _state(statuses, "evcs_current").state == "not_configured"


def test_empty_binding_values_count_as_unmapped():
    assert "ess_limits" not in available_functions(
        {**LIMITS, "set_ess_discharge_power_limit": ""}
    )


def test_active_power_needs_limits_too():
    assert available_functions({"set_ess_active_power": "number.active"}) == set()
    assert {"ess_limits", "ess_active"} <= available_functions(
        {"set_ess_active_power": "number.active", **LIMITS}
    )


def test_fields_scope_limits_functions_to_one_entity():
    ev_fields = ("sens_evcs_active_power", "set_evcs_max_current", "set_evcs_mode")
    ids = [s.function.id for s in function_statuses({}, fields=ev_fields)]
    assert ids == ["evcs_current"]


def test_limits_only_does_not_warn_about_force_mode():
    assert incomplete_function_messages({**LIMITS}) == []
    assert _state(function_statuses({**LIMITS}), "ess_active").state == "not_configured"
    assert incomplete_function_messages({}) == []


def test_active_power_without_limits_warns():
    messages = incomplete_function_messages(
        {"set_ess_active_power": "number.active"},
        labels={
            "set_ess_charge_power_limit": "Ladegrenze",
            "set_ess_discharge_power_limit": "Entladegrenze",
        },
    )
    assert len(messages) == 1
    assert "Speicher zwingen" in messages[0]
    assert "Ladegrenze" in messages[0] and "Entladegrenze" in messages[0]
    assert "Automatik" in messages[0]


@pytest.fixture
def huawei_bench():
    package = load_archetype("huawei_en")
    store = package.build_store()
    _server, base_url = start_mock_rest(store, host="127.0.0.1", port=0, token=DEFAULT_BENCH_TOKEN)
    adapter = HaAdapter(
        HaConfig(
            base_url=base_url,
            token=DEFAULT_BENCH_TOKEN,
            adapter_id="earnie-hems",
            entities=dict(package.ehal_entities),
            sign=dict(package.ehal_sign),
        )
    )
    yield store, adapter
    stop_mock_rest()


def test_ha_limits_only_skips_active_power_without_degrading(huawei_bench):
    store, adapter = huawei_bench
    for _ in range(2):  # a second cycle must still write the limits
        err = adapter.write_setpoints(
            {
                **SETPOINT_TS,
                "set_ess_active_power": -2000.0,
                "set_ess_charge_power_limit": 3000.0,
                "set_ess_discharge_power_limit": 0.0,
            }
        )
        assert err is None
        assert adapter.last_skipped_fields() == []
        assert adapter.capabilities()["supports_ess_write"] is True
    assert store.numeric_state("number.batteries_maximum_charging_power") == pytest.approx(3000.0)
    assert store.numeric_state("number.batteries_maximum_discharging_power") == pytest.approx(0.0)


@patch("integrations.ha_adapter.requests.post")
def test_ha_active_only_mapping_writes_nothing(post_mock):
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="earnie-hems",
            entities={**TELEMETRY, "set_ess_active_power": "number.active"},
        )
    )
    assert adapter.capabilities()["supports_ess_write"] is False
    err = adapter.write_setpoints({**SETPOINT_TS, "set_ess_active_power": -1000.0})
    assert err is None
    assert adapter.last_skipped_fields() == ["set_ess_active_power"]
    post_mock.assert_not_called()


@patch("integrations.ha_adapter.requests.post")
def test_partial_limits_are_reported_as_skipped(post_mock):
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="earnie-hems",
            entities={**TELEMETRY, "set_ess_charge_power_limit": "number.charge"},
        )
    )
    err = adapter.write_setpoints(
        {
            **SETPOINT_TS,
            "set_ess_charge_power_limit": 1000.0,
            "set_ess_discharge_power_limit": 1000.0,
        }
    )
    assert err is None
    assert adapter.last_skipped_fields() == [
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
    ]
    post_mock.assert_not_called()


@patch("integrations.loxone_adapter.loxone_client.send_loxone_value")
def test_loxone_active_without_limits_is_skipped(send_mock):
    send_mock.return_value = True
    adapter = LoxoneAdapter(
        LoxoneConfig(
            adapter_id="loxone-home",
            soc_name="SoC",
            pv_power_name="PV",
            battery_power_name="Bat",
            grid_power_name="Grid",
            active_power_name="Active",
            control_cmd_name="Cmd",
        )
    )
    assert adapter.capabilities()["supports_ess_write"] is False
    err = adapter.write_setpoints(
        {**SETPOINT_TS, "adapter_id": "loxone-home", "set_ess_active_power": -1000.0}
    )
    assert err is None
    assert adapter.last_skipped_fields() == ["set_ess_active_power"]
    send_mock.assert_not_called()


def test_partial_energy_counters_are_ignored():
    adapter = MagicMock()
    adapter.read_state.return_value = {"state": "5", "attributes": {"unit_of_measurement": "kWh"}}
    partial = {"sens_pv_energy": "sensor.pv_e", "sens_grid_energy_import": "sensor.imp"}
    assert read_plant_energy_readings(adapter, entities=partial) == {}
    adapter.read_state.assert_not_called()
    full = {**partial, "sens_grid_energy_export": "sensor.exp"}
    assert read_plant_energy_readings(adapter, entities=full)


def test_write_records_mark_skipped_fields():
    rows = build_ehal_write_records(
        {"set_ess_active_power": -2000.0, "set_ess_charge_power_limit": 3000.0},
        written_at="2026-01-01T00:00:00Z",
        error=None,
        skipped=["set_ess_active_power"],
    )
    assert rows[0]["skipped"] is True and rows[0]["success"] is False
    assert rows[0]["message"] == SKIPPED_MESSAGE
    assert rows[1]["success"] is True and "skipped" not in rows[1]


def test_ha_unmapped_mode_is_reported_as_skipped(huawei_bench):
    _store, adapter = huawei_bench
    err = adapter.write_setpoints(
        {**SETPOINT_TS, "set_ess_mode": 1, "set_ess_charge_power_limit": 2000.0}
    )
    assert err is None
    assert adapter.last_skipped_fields() == []
