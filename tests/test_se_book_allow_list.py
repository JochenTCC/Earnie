"""SE sunrise book slice: explicit flex_indices bind every flex consumer (incl. EV deadline)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer.charging_schedule import (
    BOOK_INDICES_KEY,
    contexts_within_book,
    schedule_indices_for_consumer,
)
from optimizer.milp import milp_horizon_schedule
from optimizer.slot_duration import DEFAULT_DT_H

_START = datetime(2025, 12, 8, 7, 45)
_SLOTS = 16
_BOOK = list(range(8, _SLOTS))

_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_power_kw": 5.0,
    "efficiency": 0.95,
}


def _matrix() -> list[dict]:
    """Negative prices before the book lure flex into the unbooked SA₀→SA₁ part."""
    rows = []
    for index in range(_SLOTS):
        slot = _START + timedelta(minutes=15 * index)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "consumption_mode": "profile_spec",
                "expected_p_pv": 0.0,
                "expected_p_act": 0.5,
                "k_act": -20.0 if index < _BOOK[0] else 20.0,
                "k_push_act": 0.0,
            }
        )
    return rows


def _ev() -> dict:
    return {
        "id": "ev",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 1,
        "charging_schedule": {
            "enabled": True,
            "milp": {
                "live_modus_a_min_remaining_kwh": 2.8,
                "tie_break_on_epsilon": 0.001,
                "tie_break_time_epsilon": 0.0001,
            },
        },
    }


def _pump() -> dict:
    return {
        "id": "pump",
        "name": "Pumpe",
        "nominal_power_kw": 1.0,
        "min_on_quarterhours": 1,
        "daily_target_kwh": 0.5,
    }


def _ev_context() -> dict:
    return {
        "active": True,
        "deadline": _START + timedelta(minutes=15 * _SLOTS),
        "target_kwh": 3.5,
        "use_time_window": False,
    }


def test_contexts_within_book_without_slice_is_identity():
    contexts = {"ev": _ev_context()}
    assert contexts_within_book(contexts, None) is contexts


def test_contexts_within_book_copies_contexts():
    contexts = {"ev": _ev_context()}
    bound = contexts_within_book(contexts, _BOOK)
    assert bound["ev"][BOOK_INDICES_KEY] == _BOOK
    assert BOOK_INDICES_KEY not in contexts["ev"]


def test_deadline_consumer_candidates_limited_to_book():
    matrix = _matrix()
    ctx = _ev_context()
    unbound = schedule_indices_for_consumer(matrix, _SLOTS, _BOOK, _ev(), ctx)
    assert unbound == list(range(_SLOTS))
    bound = contexts_within_book({"ev": ctx}, _BOOK)["ev"]
    assert schedule_indices_for_consumer(matrix, _SLOTS, _BOOK, _ev(), bound) == _BOOK


def _schedule(flex_indices: list[int] | None) -> list[dict]:
    return milp_horizon_schedule(
        _matrix(),
        current_soc=50.0,
        battery_params=_BATTERY,
        k_push=0.0,
        verbose=False,
        consumers=[_ev(), _pump()],
        consumer_remaining_kwh={"ev": 3.5, "pump": 0.5},
        flex_indices=flex_indices,
        charging_contexts={"ev": _ev_context()},
    )


def _energy(schedule: list[dict], cid: str, indices) -> float:
    return sum(
        float(schedule[t]["consumer_powers"].get(cid, 0.0) or 0.0) * DEFAULT_DT_H
        for t in indices
    )


def test_unbound_milp_parks_flex_before_book():
    """Without an explicit slice (Live) negative prices pull flex before the book."""
    schedule = _schedule(None)
    assert _energy(schedule, "ev", range(_BOOK[0])) > 0.0


def test_book_slice_blocks_all_flex_outside_book():
    """Regression Bug B: EV deadline and generic flex stay inside [SA₁, SA₂)."""
    schedule = _schedule(_BOOK)
    assert len(schedule) == _SLOTS
    for cid in ("ev", "pump"):
        assert _energy(schedule, cid, range(_BOOK[0])) == pytest.approx(0.0, abs=1e-9)
    assert _energy(schedule, "ev", _BOOK) == pytest.approx(3.5, abs=0.01)
    assert _energy(schedule, "pump", _BOOK) >= 0.5 - 0.01
