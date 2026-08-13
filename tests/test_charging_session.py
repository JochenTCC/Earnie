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

    def test_fulfilled_session_survives_deadline_as_plug_latch(self):
        consumer = _eauto_consumer()
        contexts = {
            "eauto": {
                "active": True,
                "plugged_in": True,
                "deadline": datetime(2026, 6, 28, 9, 30),
                "target_kwh": 10.0,
            }
        }
        raw = {
            "date": "2026-06-27",
            "delivered": {},
            "charging_sessions": {
                "eauto": {
                    "target_kwh": 10.0,
                    "delivered_kwh": 10.0,
                    "deadline": "2026-06-27T09:30:00",
                }
            },
            "plug_cycle_fulfilled": {},
        }
        state = cs.normalize_consumer_state(
            raw,
            "2026-06-27",
            contexts,
            {"eauto": consumer},
            now=datetime(2026, 6, 27, 10, 0),
        )
        assert "eauto" not in state["charging_sessions"]
        assert state["plug_cycle_fulfilled"].get("eauto") is True

    def test_unplug_clears_plug_cycle_fulfilled(self):
        consumer = _eauto_consumer()
        contexts = {
            "eauto": {
                "active": False,
                "plugged_in": False,
                "deadline": None,
                "target_kwh": 0.0,
            }
        }
        raw = {
            "date": "2026-06-27",
            "delivered": {},
            "charging_sessions": {},
            "plug_cycle_fulfilled": {"eauto": True},
        }
        state = cs.normalize_consumer_state(
            raw,
            "2026-06-27",
            contexts,
            {"eauto": consumer},
            now=datetime(2026, 6, 27, 10, 0),
        )
        assert "eauto" not in state["plug_cycle_fulfilled"]

    def test_open_charging_deadline_set_while_plugged(self):
        consumer = _eauto_consumer()
        deadline = datetime(2026, 8, 8, 13, 0)
        contexts = {
            "eauto": {
                "active": True,
                "plugged_in": True,
                "deadline": deadline,
                "target_kwh": 10.0,
            }
        }
        state = cs.normalize_consumer_state(
            {"date": "2026-08-08", "delivered": {}, "charging_sessions": {}},
            "2026-08-08",
            contexts,
            {"eauto": consumer},
            now=datetime(2026, 8, 8, 9, 0),
        )
        assert state["open_charging_deadlines"]["eauto"] == "2026-08-08T13:00:00"

    def test_open_charging_deadline_survives_unplug(self):
        consumer = _eauto_consumer()
        contexts = {
            "eauto": {
                "active": True,
                "plugged_in": False,
                "anticipated": True,
                "deadline": datetime(2026, 8, 8, 13, 0),
                "target_kwh": 8.0,
            }
        }
        raw = {
            "date": "2026-08-08",
            "delivered": {},
            "charging_sessions": {},
            "open_charging_deadlines": {"eauto": "2026-08-08T13:00:00"},
        }
        state = cs.normalize_consumer_state(
            raw,
            "2026-08-08",
            contexts,
            {"eauto": consumer},
            now=datetime(2026, 8, 8, 10, 0),
        )
        assert state["open_charging_deadlines"]["eauto"] == "2026-08-08T13:00:00"

    def test_open_charging_deadline_cleared_when_fulfilled(self):
        consumer = _eauto_consumer()
        contexts = {
            "eauto": {
                "active": False,
                "plugged_in": True,
                "deadline": None,
                "target_kwh": 0.0,
                "source_label": (
                    "session (angeschlossen, Ladeziel im Plug-Zyklus erfüllt — FertigUm ignoriert)"
                ),
            }
        }
        raw = {
            "date": "2026-08-08",
            "delivered": {},
            "charging_sessions": {},
            "open_charging_deadlines": {"eauto": "2026-08-08T13:00:00"},
            "plug_cycle_fulfilled": {"eauto": True},
        }
        state = cs.normalize_consumer_state(
            raw,
            "2026-08-08",
            contexts,
            {"eauto": consumer},
            now=datetime(2026, 8, 8, 10, 0),
        )
        assert "eauto" not in state["open_charging_deadlines"]


class TestDump20260813PrematureFulfill:
    """debug_dump_20260813_075350: Ist-SOC remaining 6.75 kWh, booked ~6.3 kWh."""

    def test_shrinking_ist_soc_does_not_overwrite_session_target(self):
        consumer = _eauto_consumer()
        deadline = datetime(2026, 8, 13, 7, 45)
        sessions = {
            "eauto": {
                "target_kwh": 11.667,
                "delivered_kwh": 6.3,
                "deadline": "2026-08-13T07:45:00",
            }
        }
        contexts = {
            "eauto": {
                "active": True,
                "plugged_in": True,
                "deadline": deadline,
                "target_kwh": 6.75,
            }
        }
        cs.sync_charging_sessions(
            sessions, contexts, {"eauto": consumer}, datetime(2026, 8, 13, 3, 15)
        )
        assert sessions["eauto"]["target_kwh"] == pytest.approx(11.667)
        cs.add_session_delivery(sessions, "eauto", 0.895)
        assert cs.session_target_fulfilled(sessions["eauto"]) is False

    def test_plugged_in_remaining_is_ist_soc_not_booked_minus(self):
        rem = cs.charging_session_remaining_kwh(
            {"plugged_in": True, "target_kwh": 6.75},
            daily_target=6.75,
            delivered_kwh=6.3,
        )
        assert rem == pytest.approx(6.75)

    def test_absent_remaining_still_subtracts_delivered(self):
        rem = cs.charging_session_remaining_kwh(
            {"plugged_in": False, "anticipated": True, "target_kwh": 11.5},
            daily_target=11.5,
            delivered_kwh=2.0,
        )
        assert rem == pytest.approx(9.5)


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
