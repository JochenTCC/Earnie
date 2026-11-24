"""Reserve P4: the idle drain is not in the MILP plan; the simulation still drains.

Regression: a learned drain of 0.012 kW added one binary per slot (big-M on the capacity); on a slow
CPU the strict solver stage found no good incumbent within its time limit and the plan fell into the
10 % gap stage. A few Wh per slot do not justify that, and the plan is renewed every cycle from the
measured SoC, so the MILP leaves the drain out (decision 2026-11-24). The simulation
(``apply_soc_change``), the reserve hold cost and the band keep it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer import battery as bat
from optimizer.milp import _solve_milp_to_model, milp_horizon_schedule

DT_H = 0.25
CAPACITY = 15.0
DRAIN_KW = 0.125
BATTERY = {
    "id": "haus",
    "battery_capacity_kwh": CAPACITY,
    "max_power_kw": 5.0,
    "min_soc": 5.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
    "threshold_power": 0.02,
}
DRAINING = {**BATTERY, bat.IDLE_DRAIN_KEY: DRAIN_KW}


def _matrix(prices: list[float]) -> list[dict]:
    start = datetime(2025, 11, 21)
    return [
        {
            "hour": (start + timedelta(minutes=15 * t)).hour,
            "date": start.date(),
            "slot_datetime": start + timedelta(minutes=15 * t),
            "expected_p_pv": 0.0,
            "expected_p_act": 0.0,
            "k_act": price,
            "k_push_act": 0.0,
        }
        for t, price in enumerate(prices)
    ]


def _variable_names(battery: dict, soc: float) -> list[str]:
    solved = _solve_milp_to_model(_matrix([30.0] * 8), soc, battery, 0.0, False, [], *([None] * 9))
    assert solved is not None
    return sorted(v.name for v in solved[0].prob.variables())


@pytest.mark.parametrize("soc", [50.0, 5.0])
def test_milp_with_drain_has_the_variables_of_one_without(soc):
    with_drain = _variable_names(DRAINING, soc)
    assert not any(name.startswith("idle_drain") for name in with_drain)
    assert with_drain == _variable_names(BATTERY, soc)


def test_idle_plan_keeps_its_soc_with_a_drain():
    schedule = milp_horizon_schedule(
        _matrix([30.0] * 8), 50.0, battery_params=DRAINING, k_push=0.0, verbose=False, consumers=[]
    )
    assert [slot["planned_soc_percent"] for slot in schedule] == [50.0] * 8
    assert all(slot["milp_plan"]["p_charge"] <= 1e-6 for slot in schedule)


def test_simulation_still_drains_down_to_the_floor():
    kwargs = bat.idle_drain_kwargs(DRAINING)
    soc, power = bat.apply_soc_change(50.0, 0.0, CAPACITY, 0.95, 5.0, 100.0, dt_h=DT_H, **kwargs)
    assert power == 0.0
    assert soc == pytest.approx(50.0 - DRAIN_KW * DT_H / CAPACITY * 100.0)
    soc, _ = bat.apply_soc_change(5.0, 0.0, CAPACITY, 0.95, 5.0, 100.0, dt_h=DT_H, **kwargs)
    assert soc == pytest.approx(5.0)
