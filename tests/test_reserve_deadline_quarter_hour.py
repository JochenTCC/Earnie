"""Virtual-reserve refill deadline window with quarter-hour slots (exact slot times, no hour floor)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pulp
import pytest

from optimizer.milp_horizon_extras import _add_virtual_reserve_deadline_charge

_DT_H = 0.25
_START = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)


def _model(horizon: int = 12, start: datetime = _START):
    prob = pulp.LpProblem("reserve_qh", pulp.LpMinimize)
    p_charge = [pulp.LpVariable(f"c{t}", lowBound=0) for t in range(horizon)]
    model = SimpleNamespace(prob=prob, horizon=horizon, p_charge=p_charge, dt_h=_DT_H)
    matrix = [
        {"slot_datetime": start + timedelta(minutes=15 * t), "hour": (start + timedelta(minutes=15 * t)).hour}
        for t in range(horizon)
    ]
    return model, matrix


def _slots(model) -> list[int]:
    constraint = model.prob.constraints["virtual_reserve_deadline_charge"]
    return sorted(int(var.name[1:]) for var in constraint.keys())


def _add(model, matrix, deadline, refill_kwh=1.0):
    _add_virtual_reserve_deadline_charge(
        model,
        matrix=matrix,
        refill_kwh=refill_kwh,
        max_charge_kw=4.0,
        efficiency=1.0,
        deadline=deadline,
    )


def test_quarter_hour_deadline_excludes_slots_after_it():
    # Deadline 10:15: only the 10:00 slot ends by then (10:15, 10:30, 10:45 start after it).
    model, matrix = _model()
    _add(model, matrix, _START + timedelta(minutes=15))
    assert _slots(model) == [0]


def test_quarter_hour_deadline_on_full_hour():
    model, matrix = _model()
    _add(model, matrix, _START + timedelta(hours=1, minutes=30))
    assert _slots(model) == [0, 1, 2, 3, 4, 5]


def test_slot_ending_after_unaligned_deadline_does_not_count():
    # Deadline 10:40: the 10:30 slot starts before but ends 10:45 > deadline → excluded.
    model, matrix = _model()
    _add(model, matrix, _START + timedelta(minutes=40))
    assert _slots(model) == [0, 1]


def test_deadline_inside_first_slot_is_overdue(caplog):
    # 10:10 is before the end of the first slot (10:15): no slot fits, refill as soon as possible.
    model, matrix = _model()
    with caplog.at_level(logging.WARNING):
        _add(model, matrix, _START + timedelta(minutes=10), refill_kwh=1.5)
    # 1.5 kWh at 4 kW × 0.25 h = 1 kWh per slot → the first two slots.
    assert _slots(model) == [0, 1]
    assert "abgelaufen" in caplog.text


def test_deadline_beyond_horizon_uses_all_slots():
    model, matrix = _model(horizon=8)
    _add(model, matrix, _START + timedelta(hours=5))
    assert _slots(model) == list(range(8))


def test_local_slot_times_compare_with_utc_deadline():
    # Slots in Europe/Vienna (UTC+1 in November); 11:15 local = 10:15 UTC.
    vienna = ZoneInfo("Europe/Vienna")
    model, matrix = _model(start=datetime(2026, 11, 18, 11, tzinfo=vienna))
    _add(model, matrix, _START + timedelta(minutes=45))
    assert _slots(model) == [0, 1, 2]


def test_row_without_slot_datetime_fails_loud():
    model, matrix = _model()
    matrix[2] = {"hour": 10}
    with pytest.raises(ValueError, match="Matrix-Slot 2"):
        _add(model, matrix, _START + timedelta(hours=2))


def test_naive_slot_datetime_fails_loud():
    model, matrix = _model()
    matrix[0] = {"slot_datetime": datetime(2026, 11, 18, 10), "hour": 10}
    with pytest.raises(ValueError, match="Zeitzone"):
        _add(model, matrix, _START + timedelta(hours=2))


def test_naive_deadline_fails_loud():
    model, matrix = _model()
    with pytest.raises(ValueError, match="ohne Zeitzone"):
        _add(model, matrix, datetime(2026, 11, 18, 11))


def test_refill_through_milp_entry_uses_exact_quarter_hours():
    from optimizer.milp import _add_virtual_reserve_refill

    model, matrix = _model()
    primary = {
        "_virtual_reserve_refill_kwh": 1.0,
        "_virtual_reserve_refill_deadline_utc": "2026-11-18T10:30:00Z",
        "max_charge_power_kw": 4.0,
    }
    _add_virtual_reserve_refill(model, matrix, primary)
    assert _slots(model) == [0, 1]
