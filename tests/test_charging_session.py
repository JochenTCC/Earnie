"""Tests für Ladesessions über Mitternacht und Deadline-Hilfsfunktionen."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer import charging_context as cc
from optimizer import charging_session as cs


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "charging_schedule": {"enabled": True},
    }


def _hour_matrix(start: datetime, hours: int = 24) -> list:
    return [
        {
            "slot_datetime": start + timedelta(hours=i),
            "hour": (start + timedelta(hours=i)).hour,
            "date": (start + timedelta(hours=i)).date(),
        }
        for i in range(hours)
    ]


class TestChargingSessionState:
    def test_session_survives_midnight_reset(self):
        consumer = _eauto_consumer()
        contexts = {
            "eauto": {
                "active": True,
                "deadline": datetime(2026, 6, 27, 9, 30),
                "target_kwh": 16.0,
            }
        }
        raw = {
            "date": "2026-06-26",
            "delivered": {"eauto": 2.0, "swimspa": 1.0},
            "charging_sessions": {
                "eauto": {
                    "target_kwh": 16.0,
                    "delivered_kwh": 2.0,
                    "deadline": "2026-06-27T09:30:00",
                }
            },
        }
        state = cs.normalize_consumer_state(
            raw,
            "2026-06-27",
            contexts,
            {"eauto": consumer},
            now=datetime(2026, 6, 27, 5, 0),
        )

        assert state["delivered"] == {}
        assert state["charging_sessions"]["eauto"]["delivered_kwh"] == 2.0

    def test_session_removed_after_deadline(self):
        consumer = _eauto_consumer()
        raw = {
            "date": "2026-06-27",
            "delivered": {},
            "charging_sessions": {
                "eauto": {
                    "target_kwh": 16.0,
                    "delivered_kwh": 10.0,
                    "deadline": "2026-06-27T09:30:00",
                }
            },
        }
        state = cs.normalize_consumer_state(
            raw,
            "2026-06-27",
            None,
            {"eauto": consumer},
            now=datetime(2026, 6, 27, 10, 0),
        )

        assert "eauto" not in state["charging_sessions"]


class TestDeadlineHelpers:
    def test_schedule_indices_cross_midnight(self):
        consumer = _eauto_consumer()
        start = datetime(2026, 6, 26, 22, 0)
        matrix = _hour_matrix(start, 24)
        ctx = {
            "active": True,
            "deadline": datetime(2026, 6, 27, 9, 30),
            "use_time_window": False,
        }
        indices = cc.schedule_indices_for_consumer(
            matrix, 24, [0, 1], consumer, ctx
        )
        assert len(indices) == 12
        assert indices[0] == 0
        assert indices[-1] == 11

    def test_urgent_indices_start_before_deadline(self):
        start = datetime(2026, 6, 27, 5, 0)
        matrix = _hour_matrix(start, 6)
        deadline = datetime(2026, 6, 27, 9, 30)
        eligible = list(range(6))
        urgent = cc.urgent_charging_indices(matrix, eligible, deadline, 16.0, 3.5)
        first_slot = cc.matrix_slot_datetime(matrix, urgent[0])
        assert first_slot >= cc.latest_start_datetime(deadline, 16.0, 3.5)

    def test_split_eligible_separates_optional_and_urgent(self):
        start = datetime(2026, 6, 28, 9, 0)
        matrix = _hour_matrix(start, 24)
        deadline = datetime(2026, 6, 29, 7, 45)
        eligible = list(range(23))
        pre, urgent = cc.split_eligible_by_urgent_deadline(
            matrix, eligible, deadline, 8.0, 3.5
        )
        assert pre
        assert urgent
        assert set(pre) & set(urgent) == set()
        assert set(pre) | set(urgent) == set(eligible)
        assert cc.matrix_slot_datetime(matrix, pre[-1]) < cc.latest_start_datetime(
            deadline, 8.0, 3.5
        )
        assert cc.matrix_slot_datetime(matrix, urgent[0]) >= cc.latest_start_datetime(
            deadline, 8.0, 3.5
        )
