"""flex_book_hours / flex_book_start (compat; sunrise book steps in test_sunrise_book_steps)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from optimizer.simulation import _flex_indices_for_book_hours, simulate_horizon

os.environ.setdefault("EARNIE_OFFLINE", "1")

_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
}


def test_flex_indices_none_uses_full_remaining():
    assert _flex_indices_for_book_hours(40, 0, None) == list(range(40))
    assert _flex_indices_for_book_hours(30, 10, None) == list(range(30))


def test_flex_indices_clamps_to_absolute_book_window():
    assert _flex_indices_for_book_hours(40, 0, 24) == list(range(24))
    assert _flex_indices_for_book_hours(30, 20, 24) == list(range(4))
    assert _flex_indices_for_book_hours(20, 24, 24) == []
    assert _flex_indices_for_book_hours(10, 30, 24) == []


def _matrix(n: int = 40) -> list[dict]:
    start = datetime(2025, 6, 1, 0, 0, 0)
    rows = []
    for h in range(n):
        slot = start + timedelta(hours=h)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 0.5,
                "expected_p_act": 1.0,
                "k_act": 20.0,
                "k_push_act": 5.0,
            }
        )
    return rows


def test_simulate_horizon_passes_clamped_flex_indices():
    matrix = _matrix(40)
    schedule = [
        {
            "milp_plan": {
                "p_grid_buy": 0.0,
                "p_grid_sell": 0.0,
                "p_charge": 0.0,
                "p_discharge": 0.0,
            },
            "consumer_powers": {},
            "consumer_pv_follow": {},
            "planned_soc_percent": 50.0,
        }
        for _ in matrix
    ]
    with patch(
        "optimizer.simulation.milp_horizon_schedule",
        return_value=schedule,
    ) as mock_sched:
        with patch(
            "optimizer.simulation._apply_forced_grid_recharge_at_horizon_end",
            side_effect=lambda rows, soc, **kw: soc,
        ):
            rows = simulate_horizon(
                matrix,
                50.0,
                battery_params=_BATTERY,
                verbose=False,
                flexible_consumers=[],
                commit_hours=len(matrix),
                flex_book_hours=24,
                disable_horizon_soc_anchor=True,
            )
    assert len(rows) == 40
    assert mock_sched.call_count == 1
    assert mock_sched.call_args.kwargs["flex_indices"] == list(range(24))


def test_simulate_horizon_flex_book_start_offset():
    matrix = _matrix(48)
    schedule = [
        {
            "milp_plan": {
                "p_grid_buy": 0.0,
                "p_grid_sell": 0.0,
                "p_charge": 0.0,
                "p_discharge": 0.0,
            },
            "consumer_powers": {},
            "consumer_pv_follow": {},
            "planned_soc_percent": 50.0,
        }
        for _ in matrix
    ]
    with patch(
        "optimizer.simulation.milp_horizon_schedule",
        return_value=schedule,
    ) as mock_sched:
        with patch(
            "optimizer.simulation._apply_forced_grid_recharge_at_horizon_end",
            side_effect=lambda rows, soc, **kw: soc,
        ):
            simulate_horizon(
                matrix,
                50.0,
                battery_params=_BATTERY,
                verbose=False,
                flexible_consumers=[],
                commit_hours=len(matrix),
                flex_book_hours=24,
                flex_book_start=24,
                disable_horizon_soc_anchor=True,
            )
    assert mock_sched.call_args.kwargs["flex_indices"] == list(range(24, 48))


def test_simulate_horizon_default_flex_indices_full_slice():
    matrix = _matrix(6)
    schedule = [
        {
            "milp_plan": {
                "p_grid_buy": 0.0,
                "p_grid_sell": 0.0,
                "p_charge": 0.0,
                "p_discharge": 0.0,
            },
            "consumer_powers": {},
            "consumer_pv_follow": {},
            "planned_soc_percent": 50.0,
        }
        for _ in matrix
    ]
    with patch(
        "optimizer.simulation.milp_horizon_schedule",
        return_value=schedule,
    ) as mock_sched:
        with patch(
            "optimizer.simulation._apply_forced_grid_recharge_at_horizon_end",
            side_effect=lambda rows, soc, **kw: soc,
        ):
            simulate_horizon(
                matrix,
                50.0,
                battery_params=_BATTERY,
                verbose=False,
                flexible_consumers=[],
                commit_hours=len(matrix),
                flex_book_hours=None,
            )
    assert mock_sched.call_args.kwargs["flex_indices"] == list(range(6))
