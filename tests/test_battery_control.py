"""2.6.n — battery control levels + Huawei HA force services."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from house_config.battery_control import (
    BATTERY_CONTROL_FULL,
    BATTERY_CONTROL_LIMITS_ONLY,
    BATTERY_CONTROL_READ_ONLY,
    normalize_battery_control,
)
from house_config.control_capability import control_capability_warnings
from house_config.entity_resolution import normalize_battery, resolve_battery_into_settings
from house_config.ha_ess_force import ha_ess_force_enables_ess_active, normalize_ha_ess_force
from integrations.ha_adapter import HaAdapter, HaConfig
from optimizer.battery import (
    MODE_AUTOMATIK,
    MODE_ENTLADESPERRE,
    MODE_ZWANGS_ENTLADEN,
    MODE_ZWANGS_LADEN,
    derive_control_from_milp_plan,
)
from optimizer.deviation_eval import _mode_is_forced_charge, _mode_is_forced_discharge
from optimizer.deviation_facts import BatteryFacts, SlotDeviationFacts
from optimizer.milp_horizon import _add_control_slot_constraints
import pulp


def _battery_raw(**overrides):
    base = {
        "id": "b1",
        "battery_capacity_kwh": 10.0,
        "battery_max_power_kw": 5.0,
        "battery_efficiency": 0.95,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
    }
    base.update(overrides)
    return base


def test_normalize_battery_control_default_full():
    bat = normalize_battery(_battery_raw(), 0)
    assert bat["control"] == BATTERY_CONTROL_FULL


def test_normalize_battery_control_limits_only():
    bat = normalize_battery(_battery_raw(control="limits_only"), 0)
    assert bat["control"] == BATTERY_CONTROL_LIMITS_ONLY


def test_normalize_battery_control_rejects_unknown():
    with pytest.raises(ValueError, match="control"):
        normalize_battery_control("nope", battery_id="b1", index=0)


def test_resolve_battery_carries_control():
    bat = normalize_battery(_battery_raw(control="read_only"), 0)
    resolved = resolve_battery_into_settings(
        {"battery_id": "b1"}, {"b1": bat}
    )
    assert resolved["battery_control"] == BATTERY_CONTROL_READ_ONLY


def test_derive_modes_full_allows_forced_charge():
    mode, power, _soc = derive_control_from_milp_plan(
        {"p_charge": 2.0, "p_discharge": 0.0, "p_grid_buy": 2.0, "p_grid_sell": 0.0},
        {"expected_p_pv": 0.0, "expected_p_act": 1.0},
        0.0,
        50.0,
        80.0,
        {
            "battery_capacity_kwh": 10.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "max_power_kw": 5.0,
            "efficiency": 0.95,
            "control": "full",
        },
        dt_h=1.0,
    )
    assert mode == MODE_ZWANGS_LADEN
    assert power > 0


def test_derive_modes_limits_only_no_forced():
    mode, power, _soc = derive_control_from_milp_plan(
        {"p_charge": 2.0, "p_discharge": 0.0, "p_grid_buy": 2.0, "p_grid_sell": 0.0},
        {"expected_p_pv": 5.0, "expected_p_act": 1.0},
        0.0,
        50.0,
        80.0,
        {
            "battery_capacity_kwh": 10.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "max_power_kw": 5.0,
            "efficiency": 0.95,
            "control": "limits_only",
        },
        dt_h=1.0,
    )
    assert mode not in (MODE_ZWANGS_LADEN, MODE_ZWANGS_ENTLADEN)
    assert mode == MODE_AUTOMATIK
    assert power == 0.0


def test_derive_modes_read_only_always_automatik():
    mode, power, soc = derive_control_from_milp_plan(
        {"p_charge": 0.0, "p_discharge": 0.0, "p_grid_buy": 0.0, "p_grid_sell": 0.0},
        {"expected_p_pv": 0.0, "expected_p_act": 3.0},
        0.0,
        55.0,
        50.0,
        {
            "battery_capacity_kwh": 10.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "max_power_kw": 5.0,
            "efficiency": 0.95,
            "control": "read_only",
        },
        dt_h=1.0,
    )
    assert mode == MODE_AUTOMATIK
    assert power == 0.0
    assert soc == 55.0


def test_limits_only_milp_constraints_forbid_charge_while_importing():
    prob = pulp.LpProblem("limits_only_slot", pulp.LpMinimize)
    p_charge = pulp.LpVariable("p_charge", lowBound=0, upBound=5)
    p_discharge = pulp.LpVariable("p_discharge", lowBound=0, upBound=5)
    p_buy = pulp.LpVariable("p_buy", lowBound=0)
    p_sell = pulp.LpVariable("p_sell", lowBound=0)
    delta_import = pulp.LpVariable("delta_import", cat="Binary")
    _add_control_slot_constraints(
        prob,
        {"control": "limits_only"},
        t=0,
        p_pv=3.0,
        p_con=1.0,
        p_flex=0.0,
        p_grid_buy=p_buy,
        p_grid_sell=p_sell,
        p_charge=p_charge,
        p_discharge=p_discharge,
        delta_import=delta_import,
        max_power=5.0,
        big_m_grid=50.0,
    )
    # Force import + charge → infeasible under limits_only
    prob += delta_import == 1
    prob += p_charge == 2
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[status] == "Infeasible"


def test_ha_ess_force_enables_ess_active():
    force = normalize_ha_ess_force(
        {"driver": "huawei_solar", "device_id": "abc", "duration_min": 20}
    )
    assert ha_ess_force_enables_ess_active(force)
    from ehal.functions import available_functions

    mapped = {
        "set_ess_charge_power_limit": "number.charge",
        "set_ess_discharge_power_limit": "number.discharge",
    }
    assert "ess_active" in available_functions(mapped, vendor_ess_active=True)
    assert "ess_active" not in available_functions(mapped, vendor_ess_active=False)


def test_control_capability_warns_full_without_ess_active():
    msgs = control_capability_warnings(
        control="full",
        ehal_map={
            "set_ess_charge_power_limit": "number.charge",
            "set_ess_discharge_power_limit": "number.discharge",
        },
    )
    assert any("full" in m for m in msgs)


def test_ha_adapter_calls_huawei_forcible_charge():
    calls: list[tuple[str, str, dict]] = []

    def _capture(domain, service, data):
        calls.append((domain, service, dict(data)))

    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha.test",
            token="t",
            adapter_id="test",
            entities={
                "set_ess_charge_power_limit": "number.charge",
                "set_ess_discharge_power_limit": "number.discharge",
            },
            ha_ess_force={
                "driver": "huawei_solar",
                "device_id": "dev-luna",
                "duration_min": 20,
            },
        )
    )
    assert adapter._supports_ess_active is True
    with patch.object(adapter, "call_service", side_effect=_capture):
        with patch.object(adapter, "_try_setpoint_write", return_value=(True, None, "")):
            err = adapter.write_setpoints(
                {
                    "schema_version": 3,
                    "ts": "2026-01-01T00:00:00Z",
                    "adapter_id": "test",
                    "set_ess_active_power": -1500,
                    "set_ess_charge_power_limit": 5000,
                    "set_ess_discharge_power_limit": 0,
                    "set_ess_mode": 1,
                }
            )
    assert err is None
    assert any(c[1] == "forcible_charge" for c in calls)
    charge_call = next(c for c in calls if c[1] == "forcible_charge")
    assert charge_call[0] == "huawei_solar"
    assert charge_call[2]["device_id"] == "dev-luna"
    assert charge_call[2]["power"] == 1500
    assert charge_call[2]["duration"] == 20


def test_ha_adapter_stops_huawei_force_on_automatik():
    calls: list[str] = []

    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha.test",
            token="t",
            adapter_id="test",
            entities={
                "set_ess_charge_power_limit": "number.charge",
                "set_ess_discharge_power_limit": "number.discharge",
            },
            ha_ess_force={
                "driver": "huawei_solar",
                "device_id": "dev-luna",
                "duration_min": 20,
            },
        )
    )
    with patch.object(
        adapter,
        "call_service",
        side_effect=lambda d, s, data: calls.append(s),
    ):
        with patch.object(adapter, "_try_setpoint_write", return_value=(True, None, "")):
            adapter.write_setpoints(
                {
                    "schema_version": 3,
                    "ts": "2026-01-01T00:00:00Z",
                    "adapter_id": "test",
                    "set_ess_charge_power_limit": 5000,
                    "set_ess_discharge_power_limit": 5000,
                    "set_ess_mode": 0,
                }
            )
    assert "stop_forcible_charge" in calls


def test_deviation_forced_predicates_gated_by_control():
    facts_limits = SlotDeviationFacts(
        slot_quality="present",
        consumers={},
        battery=BatteryFacts(
            soll_mode=MODE_ZWANGS_LADEN,
            soll_power_kw=2.0,
            soll_plan_kw=-2.0,
            ist_power_kw=0.0,
            control=BATTERY_CONTROL_LIMITS_ONLY,
        ),
        thermal={},
        charging_contexts={},
        consumer_remaining_kwh={},
        filter_windows={},
        slot_start=None,
    )
    assert _mode_is_forced_charge(facts_limits, "", {}, {}, {}) is False
    facts_full = SlotDeviationFacts(
        slot_quality="present",
        consumers={},
        battery=BatteryFacts(
            soll_mode=MODE_ZWANGS_LADEN,
            soll_power_kw=2.0,
            soll_plan_kw=-2.0,
            ist_power_kw=0.0,
            control=BATTERY_CONTROL_FULL,
        ),
        thermal={},
        charging_contexts={},
        consumer_remaining_kwh={},
        filter_windows={},
        slot_start=None,
    )
    assert _mode_is_forced_charge(facts_full, "", {}, {}, {}) is True
    assert _mode_is_forced_discharge(facts_full, "", {}, {}, {}) is False


def test_house_sim_huawei_force_updates_setpoints():
    from house_sim.core.archetype import load_archetype
    from house_sim.state_store import StateStore
    from house_sim.stepper import setpoints_from_store

    package = load_archetype("huawei_en")
    store = StateStore(list(package.entities))
    status, _ = store.apply_service(
        "huawei_solar",
        "forcible_charge",
        {"device_id": "dev1", "power": 2000, "duration": 20},
    )
    assert status == 200
    setpoints = setpoints_from_store(store, package)
    assert setpoints.active_power_w == pytest.approx(-2000.0)
    assert setpoints.self_consumption is False
    store.apply_service(
        "huawei_solar", "stop_forcible_charge", {"device_id": "dev1"}
    )
    setpoints2 = setpoints_from_store(store, package)
    assert setpoints2.self_consumption is True


def test_derive_entladesperre_still_allowed_for_limits_only():
    mode, power, _ = derive_control_from_milp_plan(
        {"p_charge": 0.0, "p_discharge": 0.0, "p_grid_buy": 0.0, "p_grid_sell": 0.0},
        {"expected_p_pv": 0.0, "expected_p_act": 3.0},
        0.0,
        50.0,
        50.0,
        {
            "battery_capacity_kwh": 10.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "max_power_kw": 5.0,
            "efficiency": 0.95,
            "control": "limits_only",
        },
        dt_h=1.0,
    )
    assert mode == MODE_ENTLADESPERRE
    assert power == 0.0
