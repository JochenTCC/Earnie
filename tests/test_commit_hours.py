"""commit_hours / open-loop schedule extraction for SE (2.3.c.0a)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from optimizer import battery as bat
from optimizer.milp import milp_horizon_schedule, milp_optimizer
from optimizer.milp_result import _extract_milp_plan, extract_horizon_schedule
from optimizer.milp_consumers import _consumer_powers_now
from optimizer.simulation import simulate_horizon

_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
}


def _matrix_row(hour: int, day: datetime, *, price: float = 20.0) -> dict:
    slot = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    return {
        "hour": hour,
        "date": day.date(),
        "slot_datetime": slot,
        "expected_p_pv": 0.5 if 10 <= hour <= 16 else 0.0,
        "expected_p_act": 1.0,
        "k_act": price,
        "k_push_act": 5.0,
    }


def _small_matrix(n: int = 4) -> list[dict]:
    day = datetime(2025, 6, 1)
    return [_matrix_row(h, day, price=15.0 + h) for h in range(n)]


def test_commit_hours_rejects_zero():
    with pytest.raises(ValueError, match="commit_hours"):
        simulate_horizon(_small_matrix(2), 50.0, battery_params=_BATTERY, commit_hours=0)


def test_extract_horizon_schedule_t0_matches_t0_helpers():
    matrix = _small_matrix(3)
    mode, target_power, _, powers, pv_follow, plan, _ = milp_optimizer(
        matrix,
        current_hour=0,
        current_soc=50.0,
        battery_params=_BATTERY,
        k_push=5.0,
        verbose=False,
        consumers=[],
    )
    schedule = milp_horizon_schedule(
        matrix,
        current_soc=50.0,
        battery_params=_BATTERY,
        k_push=5.0,
        verbose=False,
        consumers=[],
    )
    assert len(schedule) == len(matrix)
    assert schedule[0]["milp_plan"] == plan
    derived = bat.derive_control_from_milp_plan(
        schedule[0]["milp_plan"],
        matrix[0],
        sum(schedule[0]["consumer_powers"].values()),
        50.0,
        schedule[0]["planned_soc_percent"],
        _BATTERY,
    )
    assert derived[0] == mode
    assert derived[1] == pytest.approx(target_power)
    assert schedule[0]["consumer_powers"] == powers
    assert schedule[0]["consumer_pv_follow"] == pv_follow


def test_open_loop_calls_milp_horizon_schedule_once():
    matrix = _small_matrix(4)
    real_schedule = milp_horizon_schedule(
        matrix,
        50.0,
        battery_params=_BATTERY,
        k_push=5.0,
        verbose=False,
        consumers=[],
    )
    with patch(
        "optimizer.simulation.milp_horizon_schedule",
        return_value=real_schedule,
    ) as mock_sched:
        with patch("optimizer.simulation.milp_optimizer") as mock_opt:
            rows = simulate_horizon(
                matrix,
                50.0,
                battery_params=_BATTERY,
                verbose=False,
                flexible_consumers=[],
                commit_hours=len(matrix),
            )
    assert len(rows) == len(matrix)
    assert mock_sched.call_count == 1
    assert mock_opt.call_count == 0


def test_commit_hours_one_uses_hourly_milp_optimizer():
    matrix = _small_matrix(3)
    with patch(
        "optimizer.simulation.milp_optimizer",
        side_effect=lambda *a, **k: (
            bat.MODE_AUTOMATIK,
            0.0,
            50.0,
            {},
            {},
            {"p_grid_buy": 0.0, "p_grid_sell": 0.0, "p_charge": 0.0, "p_discharge": 0.0},
            {},
        ),
    ) as mock_opt:
        with patch("optimizer.simulation.milp_horizon_schedule") as mock_sched:
            rows = simulate_horizon(
                matrix,
                50.0,
                battery_params=_BATTERY,
                verbose=False,
                flexible_consumers=[],
                commit_hours=1,
            )
    assert len(rows) == 3
    assert mock_opt.call_count == 3
    assert mock_sched.call_count == 0


def test_extract_horizon_schedule_length_matches_model_horizon():
    model = MagicMock()
    model.horizon = 5
    model.p_grid_buy = [MagicMock(varValue=0.1 * t) for t in range(5)]
    model.p_grid_sell = [MagicMock(varValue=0.0) for _ in range(5)]
    model.p_charge = [MagicMock(varValue=0.0) for _ in range(5)]
    model.p_discharge = [MagicMock(varValue=0.0) for _ in range(5)]
    model.e_batt = [MagicMock(varValue=5.0) for _ in range(5)]
    model.planned_consumers = []
    model.consumer_p = {}
    model.consumer_on = {}
    model.consumer_pv_follow = {}
    model.consumer_milp_charge_kw = {}
    slots = extract_horizon_schedule(model, _BATTERY)
    assert len(slots) == 5
    assert slots[0]["milp_plan"] == _extract_milp_plan(model)
    assert _consumer_powers_now(model)[0] == slots[0]["consumer_powers"]
