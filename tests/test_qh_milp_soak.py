"""2.5.h: light soak — Live-sized QH MILP stays under HiGHS time budget."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from optimizer.cbc_solver import resolve_milp_solver
from optimizer.milp import milp_horizon_schedule
from optimizer.slot_duration import DEFAULT_DT_H


def _qh_matrix(n: int = 192) -> list[dict]:
    start = datetime(2026, 6, 15, 10, 0)
    rows = []
    for i in range(n):
        slot = start + timedelta(hours=DEFAULT_DT_H * i)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 1.0 if 8 <= slot.hour <= 18 else 0.0,
                "expected_p_act": 0.8,
                "k_act": 15.0 + (i % 8),
                "k_push_act": 5.0,
                "expected_flex_kw": {},
            }
        )
    return rows


_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
}


@pytest.mark.skipif(
    resolve_milp_solver() != "highs",
    reason="Soak timing probe targets HiGHS (default)",
)
def test_live_sized_qh_milp_solve_under_three_seconds():
    matrix = _qh_matrix(192)
    t0 = time.perf_counter()
    schedule = milp_horizon_schedule(
        matrix,
        current_soc=50.0,
        battery_params=_BATTERY,
        k_push=5.0,
        verbose=False,
        consumers=[],
    )
    elapsed = time.perf_counter() - t0
    assert len(schedule) == 192
    assert elapsed < 3.0
