"""The charging window of a historical context follows each slot's own day, not the ready-by day."""
from __future__ import annotations

from datetime import datetime, timedelta

from optimizer.charging_context import historical_charging_context
from optimizer.charging_schedule import consumer_charging_eligible_indices

CONSUMER = {
    "id": "ev",
    "charging_schedule": {
        "enabled": True,
        "weekday": {"car_available_from_hour": 18, "ready_by_hour": 7},
        "weekend": {"car_available_from_hour": 9, "ready_by_hour": 8},
    },
}
FRIDAY_NOON = datetime(2025, 2, 21, 12, 0)
SATURDAY_READY = datetime(2025, 2, 22, 8, 0)


def _matrix() -> list[dict]:
    slots = int((SATURDAY_READY - FRIDAY_NOON) / timedelta(minutes=15))
    return [
        {
            "slot_datetime": FRIDAY_NOON + timedelta(minutes=15 * index),
            "date": (FRIDAY_NOON + timedelta(minutes=15 * index)).date(),
            "charging_anchor": SATURDAY_READY,
        }
        for index in range(slots)
    ]


def _eligible_slots(monkeypatch) -> set[datetime]:
    monkeypatch.setattr(
        "optimizer.targets.resolve_horizon_consumer_targets_kwh",
        lambda _matrix, targets, **_kwargs: dict(targets),
    )
    matrix = _matrix()
    context = historical_charging_context(
        CONSUMER, matrix, {"ev": 10.0}, FRIDAY_NOON, realtime=False
    )
    indices = consumer_charging_eligible_indices(matrix, CONSUMER, list(range(len(matrix))), context)
    return {matrix[t]["slot_datetime"] for t in indices}


def test_friday_before_arrival_stays_closed_for_a_saturday_ready_by(monkeypatch) -> None:
    eligible = _eligible_slots(monkeypatch)
    assert datetime(2025, 2, 21, 12, 0) not in eligible
    assert datetime(2025, 2, 21, 17, 45) not in eligible
    assert datetime(2025, 2, 21, 18, 0) in eligible


def test_saturday_night_uses_the_weekend_window(monkeypatch) -> None:
    eligible = _eligible_slots(monkeypatch)
    assert datetime(2025, 2, 22, 3, 0) in eligible
    assert datetime(2025, 2, 22, 7, 45) in eligible
