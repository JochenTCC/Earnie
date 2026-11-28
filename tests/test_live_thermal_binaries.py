"""Live thermal on/off decisions are binary only in the first hours of the plan.

Regression (REG-76, 2026-11-27): with the pool store and the heat pump planned over the whole
Live horizon, the strict solve of a 181-slot cycle did not end in ten minutes; binaries only in
the near horizon bring it back to about a second.
"""
from __future__ import annotations

from types import SimpleNamespace

import pulp
import pytest

from optimizer.live_thermal_binaries import (
    LIVE_THERMAL_BINARY_HOURS,
    live_thermal_binary_slots,
    relax_far_live_thermal_binaries,
)


def _model(consumers: list[dict], horizon: int = 96, dt_h: float = 0.25):
    on = {
        str(c["id"]): [pulp.LpVariable(f"{c['id']}_on_{t}", cat=pulp.LpBinary) for t in range(horizon)]
        for c in consumers
    }
    return SimpleNamespace(
        dt_h=dt_h,
        planned_consumers=consumers,
        consumer_on=on,
        consumer_milp_charge_kw={str(c["id"]): 2.0 for c in consumers},
        consumer_p={},
    )


_HP = {"id": "wp", "type": "thermal_annual", "daily_target_source": "thermal_annual"}
_POOL = {"id": "pool", "daily_target_source": "thermal"}
_EV = {"id": "ev", "type": "ev"}


@pytest.fixture
def thermal_kinds(monkeypatch):
    monkeypatch.setattr(
        "optimizer.thermal_flex_base.is_thermal_flex_consumer", lambda c: c["id"] == "wp"
    )
    monkeypatch.setattr(
        "optimizer.thermal_flex_context.is_heating_rod_consumer", lambda c: False
    )


def _live(monkeypatch, value: bool) -> None:
    monkeypatch.setattr("optimizer.live_cycle_scope.is_live_thermal_planning", lambda _m: value)


def test_binary_window_is_twelve_hours_of_slots():
    assert LIVE_THERMAL_BINARY_HOURS == 12.0
    assert live_thermal_binary_slots(0.25) == 48
    assert live_thermal_binary_slots(1.0) == 12


def test_live_relaxes_far_thermal_slots_only(monkeypatch, thermal_kinds):
    _live(monkeypatch, True)
    model = _model([_HP, _POOL, _EV])
    relaxed = relax_far_live_thermal_binaries(model, [{}] * 96, None)
    assert sorted(relaxed) == ["pool", "wp"]
    for cid in ("wp", "pool"):
        cats = [var.cat for var in model.consumer_on[cid]]
        assert set(cats[:48]) == {pulp.LpInteger}
        assert set(cats[48:]) == {pulp.LpContinuous}
        assert all(var.upBound == 1 and var.lowBound == 0 for var in model.consumer_on[cid])
    assert {var.cat for var in model.consumer_on["ev"]} == {pulp.LpInteger}


@pytest.mark.parametrize(("is_live", "book"), [(False, None), (True, [0, 1, 2])])
def test_se_book_and_non_live_keep_all_binaries(monkeypatch, thermal_kinds, is_live, book):
    _live(monkeypatch, is_live)
    model = _model([_HP, _POOL])
    assert relax_far_live_thermal_binaries(model, [{}] * 96, book) == []
    assert {var.cat for vars_ in model.consumer_on.values() for var in vars_} == {pulp.LpInteger}


def test_pulse_starts_follow_the_on_variable_type():
    from optimizer.thermal_flex_base import add_max_pulses_per_day_constraints

    prob = pulp.LpProblem("p", pulp.LpMinimize)
    on = [pulp.LpVariable(f"on_{t}", cat=pulp.LpBinary) for t in range(4)]
    for var in on[2:]:
        var.cat = pulp.LpContinuous
    add_max_pulses_per_day_constraints(prob, on, [0, 1, 2, 3], max_pulses=1, prefix="hp")
    starts = {v.name: v.cat for v in prob.variables() if "_start_" in v.name}
    assert starts == {
        "hp_start_0": pulp.LpInteger,
        "hp_start_1": pulp.LpInteger,
        "hp_start_2": pulp.LpContinuous,
        "hp_start_3": pulp.LpContinuous,
    }


def test_relaxed_slot_counts_its_share_a_binary_still_rounds():
    from optimizer.milp_consumer_vars import _consumer_power_at, _planned_consumer_kwh_in_slots

    model = _model([_HP], horizon=2, dt_h=0.25)
    binary, relaxed = model.consumer_on["wp"]
    relaxed.cat = pulp.LpContinuous
    binary.varValue = 0.4
    relaxed.varValue = 0.4
    assert _consumer_power_at(model, _HP, 0) == 0.0
    assert _consumer_power_at(model, _HP, 1) == pytest.approx(0.8)
    assert _planned_consumer_kwh_in_slots(model, _HP, [0, 1]) == pytest.approx(0.2)
