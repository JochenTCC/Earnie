"""Tests für generic-Flex-MILP-Kontext."""
from __future__ import annotations

from datetime import datetime

from house_config.generic_schedule import eligible_start_hours
from optimizer.generic_flex_context import consumer_generic_eligible_indices


def _matrix_for_hours(hours: list[int], day: datetime) -> list[dict]:
    return [
        {
            "hour": hour,
            "date": day.date(),
            "slot_datetime": day.replace(hour=hour, minute=0, second=0, microsecond=0),
        }
        for hour in hours
    ]


def test_consumer_generic_eligible_indices_shift_zero():
    day = datetime(2023, 6, 5)
    matrix = _matrix_for_hours(list(range(24)), day)
    consumer = {
        "id": "washer",
        "generic_flex_window": {
            "start_hour": 18,
            "start_shift_h": 0.0,
            "duration_h": 2.0,
        },
    }
    eligible = consumer_generic_eligible_indices(matrix, consumer, list(range(24)))
    assert eligible == [18, 19]


def test_consumer_generic_eligible_indices_fully_free():
    day = datetime(2023, 6, 5)
    matrix = _matrix_for_hours(list(range(24)), day)
    consumer = {
        "id": "washer",
        "generic_flex_window": {
            "start_hour": 12,
            "start_shift_h": 12.0,
            "duration_h": 1.0,
        },
    }
    eligible = consumer_generic_eligible_indices(matrix, consumer, list(range(24)))
    assert eligible == list(range(24))


def test_eligible_start_hours_matches_shift_twelve():
    assert len(eligible_start_hours(5, 12.0)) == 24
