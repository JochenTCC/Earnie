"""EHAL functions: available only when all required fields are mapped."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ehal.functions import (
    available_functions,
    function_statuses,
    incomplete_function_messages,
)
from integrations.ehal_live import SKIPPED_MESSAGE, build_ehal_write_records
from integrations.ehal_write import clear_published_for_tests, load_published
from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.ha_meter_energy import read_plant_energy_readings
from integrations.loxone_adapter import LoxoneAdapter, LoxoneConfig

TELEMETRY = {
    "sens_grid_power_active": "sensor.grid",
    "inv.wr.sens_inv_power_pv": "sensor.pv",
    "ess.house.sens_ess_soc": "sensor.soc",
}
LIMITS = {
    "set_ess_charge_power_limit": "number.charge",
    "set_ess_discharge_power_limit": "number.discharge",
}
# Binding P5e activation maps (empty values) for HaAdapter.
TELEMETRY_PUSH = {k: "" for k in TELEMETRY}
LIMITS_PUSH = {k: "" for k in LIMITS}
SETPOINT_TS = {"schema_version": 4, "ts": "2026-01-01T00:00:00Z", "adapter_id": "earnie-hems"}


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


def test_ha_limits_publish_without_active_power():
    clear_published_for_tests()
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="earnie-hems",
            entities={**TELEMETRY_PUSH, **LIMITS_PUSH},
            setpoint_qids={
                "set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit",
                "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
            },
        )
    )
    err = adapter.write_setpoints(
        {
            **SETPOINT_TS,
            "set_ess_active_power": -2000.0,
            "set_ess_charge_power_limit": 3000.0,
            "set_ess_discharge_power_limit": 0.0,
        }
    )
    assert err is None
    # Never-configured active power is skipped without listing in last_skipped.
    assert adapter.last_skipped_fields() == []
    assert adapter.capabilities()["supports_ess_write"] is True
    published = load_published()
    assert published["ess.house.set_ess_charge_power_limit"] == pytest.approx(3000.0)
    assert published["ess.house.set_ess_discharge_power_limit"] == pytest.approx(0.0)


def test_ha_active_only_mapping_writes_nothing():
    clear_published_for_tests()
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="earnie-hems",
            entities={**TELEMETRY_PUSH, "set_ess_active_power": ""},
        )
    )
    assert adapter.capabilities()["supports_ess_write"] is False
    err = adapter.write_setpoints({**SETPOINT_TS, "set_ess_active_power": -1000.0})
    assert err is None
    assert adapter.last_skipped_fields() == ["set_ess_active_power"]
    assert load_published() == {}


def test_partial_limits_are_reported_as_skipped():
    clear_published_for_tests()
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="earnie-hems",
            entities={**TELEMETRY_PUSH, "set_ess_charge_power_limit": ""},
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
    assert load_published() == {}


def test_loxone_active_without_limits_is_skipped():
    adapter = LoxoneAdapter(
        LoxoneConfig(
            adapter_id="loxone-home",
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


def test_partial_energy_counters_are_ignored():
    adapter = MagicMock()
    adapter.cfg.entities = {}
    adapter.cfg.push_read_qids = {}
    partial = {"sens_pv_energy": "", "sens_grid_energy_import": ""}
    assert read_plant_energy_readings(adapter, entities=partial) == {}
    full = {**partial, "sens_grid_energy_export": ""}
    # Full activation without push qids → empty readings (no REST fallback).
    assert read_plant_energy_readings(adapter, entities=full) == {}


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


def test_ha_unmapped_mode_is_not_listed_as_incomplete_skip():
    clear_published_for_tests()
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="earnie-hems",
            entities={**LIMITS_PUSH},
            setpoint_qids={
                "set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit",
                "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
            },
        )
    )
    err = adapter.write_setpoints(
        {**SETPOINT_TS, "set_ess_mode": 1, "set_ess_charge_power_limit": 2000.0}
    )
    assert err is None
    # Unmapped mode is skipped quietly (not an incomplete-function skip).
    assert adapter.last_skipped_fields() == []
    assert load_published()["ess.house.set_ess_charge_power_limit"] == pytest.approx(
        2000.0
    )
