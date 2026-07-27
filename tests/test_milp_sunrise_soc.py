"""Tests für SOC_min-Randbedingung am Sonnenaufgang-Slot."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pulp

from optimizer.milp import (
    _add_milp_objective,
    _add_pv_only_charge_through_sunrise,
    _build_milp_model,
)
from optimizer.simulation import simulate_horizon


def _price_matrix(hours: int, cheap_first: bool = True) -> list[dict]:
    prices = [10.0, 40.0] if cheap_first else [40.0, 10.0]
    return [
        {
            "hour": h,
            "expected_p_pv": 4.0 if h < 12 else 0.0,
            "expected_p_act": 1.0,
            "k_act": prices[0 if h < hours // 2 else 1],
            "expected_flex_kw": {},
        }
        for h in range(hours)
    ]


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
    }


def test_sunrise_without_hard_eq_keeps_soc_above_min():
    """Live no longer forces e_batt[SA] == SOC_min; residual SoC may remain."""
    start_soc = 70.0
    battery_params = _battery_params()
    matrix = _price_matrix(hours=30)
    sunrise_index = 16
    model = _build_milp_model(
        matrix, 30, battery_params, start_soc, [], 0.0, {}, None
    )
    _add_milp_objective(model, matrix, 3.5, None, wear_cent_per_kwh=0.0)
    _add_pv_only_charge_through_sunrise(model, matrix, sunrise_index)

    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"

    sunrise_energy = model.e_batt[sunrise_index].varValue
    e_min = (battery_params["min_soc"] / 100.0) * battery_params["battery_capacity_kwh"]
    assert sunrise_energy is not None
    assert sunrise_energy + 1e-4 >= e_min
    # Without hard equality, overnight residual need not be dumped to e_min.
    assert sunrise_energy > e_min + 0.05


def test_pv_only_charge_blocks_night_grid_charge_before_sunrise():
    battery_params = _battery_params()
    matrix = [
        {
            "hour": 0,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 10.0,
            "k_push_act": 5.0,
            "expected_flex_kw": {},
        },
        {
            "hour": 1,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 30.0,
            "k_push_act": 5.0,
            "expected_flex_kw": {},
        },
        {
            "hour": 2,
            "expected_p_pv": 1.0,
            "expected_p_act": 0.5,
            "k_act": 20.0,
            "k_push_act": 5.0,
            "expected_flex_kw": {},
        },
    ]
    model = _build_milp_model(
        matrix, 3, battery_params, 40.0, [], 0.0, {}, None
    )
    _add_milp_objective(model, matrix, 5.0, {}, wear_cent_per_kwh=0.0)
    _add_pv_only_charge_through_sunrise(model, matrix, 1)
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    assert float(model.p_charge[0].varValue or 0.0) < 1e-6
    assert float(model.p_charge[1].varValue or 0.0) < 1e-6


def test_hourly_mpc_no_soc_spike_before_sunrise_with_ev():
    """No night grid charge spike; no forced dump to SOC_min at SA₁."""
    tz = ZoneInfo("Europe/Vienna")
    start = datetime(2026, 7, 27, 2, 0, tzinfo=tz)
    prices = [12.7, 11.9, 11.4, 18.7, 17.4]
    matrix = []
    for index, price in enumerate(prices):
        slot = start + timedelta(hours=index)
        matrix.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 0.0,
                "expected_p_act": 0.517,
                "k_act": price,
                "k_push_act": 6.46,
                "expected_flex_kw": {},
            }
        )
    battery_params = {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.97,
    }
    consumers = [
        {
            "id": "ev",
            "name": "Smart",
            "type": "ev",
            "nominal_power_kw": 3.5,
            "min_power_kw": 1.4,
            "min_on_quarterhours": 1,
            "daily_target_kwh": 4.9,
            "battery_capacity_kwh": 20.0,
        }
    ]
    charging_contexts = {
        "ev": {
            "active": True,
            "deadline": datetime(2026, 7, 27, 7, 45, tzinfo=tz),
            "target_kwh": 4.9,
            "use_time_window": False,
            "plugged_in": True,
        }
    }
    rows = simulate_horizon(
        matrix,
        19.9,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh={"ev": 4.9},
        sunrise_soc_min_index=3,
        flexible_consumers=consumers,
        charging_contexts=charging_contexts,
        commit_hours=1,
        matrix_prepared=True,
    )
    socs = [float(row["Simulierter SoC (%)"]) for row in rows]
    assert max(socs) < 35.0
    # Residual SoC must not be forced to min_soc solely by the SA₁ anchor.
    assert socs[3] >= 15.0
