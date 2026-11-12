"""MILP with a start SoC outside the battery's limits (``optimizer/milp_soc_recovery.py``).

The plan may leave the SoC where it starts and lead it back when the prices suit. Until it is
back inside the limits it only moves towards them, and once inside it stays inside. Before,
slot 0 had to reach the limit: forced grid charging or export, or no solution at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer import battery as bat
from optimizer.milp import _solve_milp_to_model, milp_horizon_schedule, milp_optimizer

DT_H = 0.25
BIG_BATTERY = {
    "id": "haus",
    "battery_capacity_kwh": 40.0,
    "max_power_kw": 5.0,
    "min_soc": 20.0,
    "max_soc": 60.0,
    "efficiency": 0.95,
}
SOC_TOLERANCE = 0.11  # planned SoC is rounded to 0.1 %
POWER_TOLERANCE_KW = 1e-6


def _matrix(prices: list[float], *, pv_kw: float = 0.0, load_kw: float = 1.0) -> list[dict]:
    start = datetime(2025, 6, 1)
    return [
        {
            "hour": 0,
            "date": start.date(),
            "slot_datetime": start + timedelta(minutes=15 * t),
            "expected_p_pv": pv_kw,
            "expected_p_act": load_kw,
            "k_act": price,
            "k_push_act": 5.0,
        }
        for t, price in enumerate(prices)
    ]


def _schedule(matrix: list[dict], soc: float, battery: dict = BIG_BATTERY) -> list[dict]:
    schedule = milp_horizon_schedule(
        matrix, soc, battery_params=battery, k_push=5.0, verbose=False, consumers=[]
    )
    # a fallback (no optimal solve) is a single slot without a planned SoC
    assert len(schedule) == len(matrix)
    assert all(slot["planned_soc_percent"] is not None for slot in schedule)
    return schedule


def _soc_chain(schedule: list[dict], start_soc: float) -> list[tuple[float, float, dict]]:
    """Per slot: SoC at its start, SoC at its end, plan."""
    chain = []
    soc = start_soc
    for slot in schedule:
        chain.append((soc, slot["planned_soc_percent"], slot["milp_plan"]))
        soc = slot["planned_soc_percent"]
    return chain


def test_start_far_below_min_soc_solves_and_only_charges_until_recovered():
    # 12 cheap slots, then 12 expensive ones: worth charging past min_soc and discharging later
    matrix = _matrix([5.0] * 12 + [60.0] * 12)
    chain = _soc_chain(_schedule(matrix, 2.0), 2.0)

    recovered = False
    for soc_start, soc_end, plan in chain:
        assert plan["p_charge"] <= BIG_BATTERY["max_power_kw"] + POWER_TOLERANCE_KW
        assert plan["p_discharge"] <= BIG_BATTERY["max_power_kw"] + POWER_TOLERANCE_KW
        if soc_start < BIG_BATTERY["min_soc"] - SOC_TOLERANCE:
            assert not recovered, "SoC fell below min_soc again after recovering"
            assert plan["p_discharge"] <= POWER_TOLERANCE_KW
            assert soc_end >= soc_start - SOC_TOLERANCE
        else:
            recovered = True
            assert soc_end >= BIG_BATTERY["min_soc"] - SOC_TOLERANCE
    assert recovered
    # the lock is not trivial: the plan does discharge once it is back above min_soc
    assert any(plan["p_discharge"] > 0.1 for _, _, plan in chain)
    # one slot at full power is +3 %: no jump to min_soc
    assert chain[0][1] <= 2.0 + 3.0 + SOC_TOLERANCE


def test_below_min_soc_without_a_price_reason_the_soc_stays():
    matrix = _matrix([20.0 + t for t in range(8)])
    chain = _soc_chain(_schedule(matrix, 2.0), 2.0)

    assert all(plan["p_charge"] <= POWER_TOLERANCE_KW for _, _, plan in chain)
    assert all(plan["p_discharge"] <= POWER_TOLERANCE_KW for _, _, plan in chain)
    assert [soc_end for _, soc_end, _ in chain] == [2.0] * 8


def test_start_far_above_max_soc_solves_and_never_charges_until_recovered():
    # PV surplus in every slot tempts the plan to charge
    matrix = _matrix([60.0] * 12 + [5.0] * 12, pv_kw=3.0, load_kw=1.0)
    chain = _soc_chain(_schedule(matrix, 100.0), 100.0)

    recovered = False
    for soc_start, soc_end, plan in chain:
        assert plan["p_discharge"] <= BIG_BATTERY["max_power_kw"] + POWER_TOLERANCE_KW
        if soc_start > BIG_BATTERY["max_soc"] + SOC_TOLERANCE:
            assert not recovered, "SoC rose above max_soc again after recovering"
            assert plan["p_charge"] <= POWER_TOLERANCE_KW
            assert soc_end <= soc_start + SOC_TOLERANCE
        else:
            recovered = True
            assert soc_end <= BIG_BATTERY["max_soc"] + SOC_TOLERANCE
    # one slot at full power is -3.3 %: no jump to max_soc
    assert chain[0][1] >= 100.0 - 3.3 - SOC_TOLERANCE


def test_slightly_below_min_soc_slot_0_is_not_forced_to_charge_from_the_grid():
    battery = {**BIG_BATTERY, "battery_capacity_kwh": 10.0, "min_soc": 10.0, "max_soc": 100.0}
    matrix = _matrix([20.0 + t for t in range(8)])

    mode, target_power, _soc, _powers, _pv, plan, _obs = milp_optimizer(
        matrix, 0, 5.0, battery_params=battery, k_push=5.0, verbose=False, consumers=[]
    )

    assert plan["p_charge"] <= POWER_TOLERANCE_KW
    assert mode != bat.MODE_ZWANGS_LADEN
    assert target_power == 0.0


def test_start_inside_the_limits_adds_no_recovery_variables():
    matrix = _matrix([20.0 + t for t in range(4)])
    solved = _solve_milp_to_model(
        matrix, 50.0, BIG_BATTERY, 5.0, False, [], None, None, None, None, None, None, None, None, None
    )
    assert solved is not None
    model = solved[0]
    assert model.relaxed_soc_bounds_percent is None
    assert not [v for v in model.prob.variables() if v.name.startswith("soc_recovered")]


def test_setpoint_below_min_soc_follows_the_plan_not_the_gap_to_min_soc():
    # plan: 2 % -> 3.5 % by grid charging; reaching min_soc (20 %) would need far more power
    mode, target_power, target_soc = bat.derive_control_from_milp_plan(
        {"p_charge": 2.5, "p_discharge": 0.0, "p_grid_buy": 3.5, "p_grid_sell": 0.0},
        {"expected_p_pv": 0.0, "expected_p_act": 1.0},
        0.0,
        2.0,
        3.5,
        BIG_BATTERY,
        dt_h=DT_H,
    )

    assert mode == bat.MODE_ZWANGS_LADEN
    assert target_soc == 3.5
    # 1.5 % of 40 kWh in a quarter hour at 95 % efficiency
    assert target_power == pytest.approx(0.6 / (0.95 * DT_H), abs=0.01)
