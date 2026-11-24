"""Buy/sell and charge/discharge binaries only in slots whose prices need them.

Splitting a signed power into two non-negative parts is exact in an LP while running both at once
cannot pay. The binaries cost solver time (338 of 1056 in a live cycle), so the MILP creates
``delta_import`` only where the sell price reaches the buy price and ``delta_charge`` only where a
price is zero or below; battery control ``limits_only`` / ``read_only`` and vendor mode keep all.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer.milp import _solve_milp_to_model
from optimizer.milp_horizon import simultaneous_flow_slots

BATTERY = {
    "id": "haus",
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 5.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
    "threshold_power": 0.02,
}


def _matrix(prices: list[tuple[float, float]], pv_kw: float = 0.0) -> list[dict]:
    start = datetime(2025, 11, 21, 10)
    return [
        {
            "hour": (start + timedelta(minutes=15 * t)).hour,
            "date": start.date(),
            "slot_datetime": start + timedelta(minutes=15 * t),
            "expected_p_pv": pv_kw,
            "expected_p_act": 1.0,
            "k_act": buy,
            "k_push_act": sell,
        }
        for t, (buy, sell) in enumerate(prices)
    ]


def _solve(matrix: list[dict], battery: dict = BATTERY, soc: float = 50.0):
    solved = _solve_milp_to_model(matrix, soc, battery, 7.0, False, [], *([None] * 9))
    assert solved is not None
    return solved[0]


def _binary_names(model) -> set[str]:
    return {v.name for v in model.prob.variables() if v.name.startswith("delta_")}


def test_ordinary_prices_need_no_exclusivity_binaries():
    model = _solve(_matrix([(30.0, 7.0), (20.0, 7.0), (40.0, 7.0), (25.0, 7.0)], pv_kw=3.0))
    assert _binary_names(model) == set()
    assert simultaneous_flow_slots(model) == {"grid": [], "battery": []}


def test_negative_buy_price_keeps_both_binaries_in_that_slot_only():
    model = _solve(_matrix([(30.0, 7.0), (-5.0, 7.0), (30.0, 7.0)], pv_kw=3.0))
    assert _binary_names(model) == {"delta_import_1", "delta_charge_haus_1"}
    assert simultaneous_flow_slots(model) == {"grid": [], "battery": []}


def test_sell_price_at_the_buy_price_keeps_the_grid_binary():
    model = _solve(_matrix([(30.0, 7.0), (7.0, 7.0)]))
    assert _binary_names(model) == {"delta_import_1"}


@pytest.mark.parametrize("control", ["limits_only", "read_only"])
def test_restricted_battery_control_keeps_every_grid_binary(control):
    model = _solve(_matrix([(30.0, 7.0), (20.0, 7.0)], pv_kw=3.0), {**BATTERY, "control": control})
    assert _binary_names(model) == {"delta_import_0", "delta_import_1"}
