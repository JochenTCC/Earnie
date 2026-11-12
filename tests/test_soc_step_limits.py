"""SoC step: the limits cut the battery action, they never create one.

A start SoC outside ``min_soc`` / ``max_soc`` (a measured value below the reserve or above the
charge limit) used to jump to the limit within one slot. The power for that jump was computed
back from the SoC gap, without the battery's power limit, and booked as grid import or export.
"""
from __future__ import annotations

import pytest

from optimizer.battery import apply_soc_change, vendor_mode_step
from optimizer.simulation import simulate_baseline_horizon

BATTERY = {
    "battery_capacity_kwh": 20.0,
    "max_power_kw": 5.0,
    "min_soc": 20.0,
    "max_soc": 90.0,
    "efficiency": 0.95,
}
DT_H = 0.25


def _step(old_soc: float, action_kw: float) -> tuple[float, float]:
    return apply_soc_change(
        old_soc,
        action_kw,
        BATTERY["battery_capacity_kwh"],
        BATTERY["efficiency"],
        BATTERY["min_soc"],
        BATTERY["max_soc"],
        dt_h=DT_H,
    )


@pytest.mark.parametrize("start_soc", [0.0, 5.0, 19.9, 90.1, 100.0])
def test_idle_battery_outside_the_limits_keeps_its_soc(start_soc):
    assert _step(start_soc, 0.0) == (start_soc, 0.0)


def test_below_min_soc_a_discharge_is_dropped_and_a_charge_is_applied():
    assert _step(5.0, -3.0) == (5.0, 0.0)
    new_soc, action = _step(5.0, 3.0)
    assert action == 3.0
    assert new_soc == pytest.approx(5.0 + 3.0 * 0.95 * DT_H / 20.0 * 100.0)
    assert new_soc < BATTERY["min_soc"]  # one slot does not reach the limit


def test_above_max_soc_a_charge_is_dropped_and_a_discharge_is_applied():
    assert _step(100.0, 3.0) == (100.0, 0.0)
    new_soc, action = _step(100.0, -3.0)
    assert action == -3.0
    assert new_soc == pytest.approx(100.0 - 3.0 / 0.95 * DT_H / 20.0 * 100.0)
    assert new_soc > BATTERY["max_soc"]


@pytest.mark.parametrize("start_soc", [0.0, 5.0, 20.0, 50.0, 90.0, 100.0])
@pytest.mark.parametrize("action_kw", [-5.0, -1.0, 0.0, 1.0, 5.0])
def test_returned_power_never_exceeds_the_requested_power(start_soc, action_kw):
    _, action = _step(start_soc, action_kw)
    assert abs(action) <= abs(action_kw) + 1e-12
    assert action * action_kw >= 0.0  # same direction, or dropped


def test_inside_the_limits_the_action_is_cut_at_the_limit():
    new_soc, action = _step(89.0, 5.0)
    assert new_soc == 90.0
    assert action == pytest.approx(0.2 / (0.95 * DT_H))
    new_soc, action = _step(21.0, -5.0)
    assert new_soc == 20.0
    assert action == pytest.approx(-0.2 * 0.95 / DT_H)


def test_vendor_mode_below_min_soc_charges_the_surplus_within_the_power_limit():
    new_soc, action = vendor_mode_step(5.0, 8.0, BATTERY, dt_h=DT_H)
    assert action == BATTERY["max_power_kw"]
    assert 5.0 < new_soc < BATTERY["min_soc"]


def test_baseline_below_min_soc_books_no_phantom_grid_charge(monkeypatch):
    monkeypatch.setattr("config.get_flexible_consumers", lambda *_a, **_k: [])
    matrix = [
        {"hour": 0, "expected_p_pv": 0.0, "expected_p_act": 0.5, "k_act": 30.0, "k_push_act": 8.0}
        for _ in range(4)
    ]

    rows = simulate_baseline_horizon(matrix, 5.0, battery_params=BATTERY, consumers=[])

    assert [row["Simulierter SoC (%)"] for row in rows] == [5.0] * 4
    assert [row["Geplante Batterie-Aktion (kW)"] for row in rows] == [0.0] * 4
    # only the house load is imported
    assert [row["Netzbezug (kW)"] for row in rows] == [0.5] * 4
