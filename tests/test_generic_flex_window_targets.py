"""Window-aware generic/EV flex targets for 07:00 backtesting anchors."""
from __future__ import annotations

from datetime import date, datetime

from house_config.generic_schedule import (
    generic_daily_target_kwh_for_day,
    generic_flex_target_kwh_for_window,
)
from house_config.planning_flex_bridge import planning_ev_daily_targets, planning_flex_daily_targets
from simulation.engine import window_anchor_for_date, window_slot_datetimes


MEIN_HAUSHALT_GENERIC = {
    "id": "standard",
    "type": "generic",
    "nominal_power_kw": 3.0,
    "annual_kwh": 2184.0,
    "schedule": {
        "runs_per_week": 7,
        "duration_h": 2.0,
        "start_hour": 16,
        "start_shift_h": 6.0,
    },
}

EV_CONSUMER = {
    "id": "ev",
    "type": "ev",
    "nominal_power_kw": 11.0,
    "battery_capacity_kwh": 40.0,
    "charging_schedule": {
        "target_soc_percent": 100.0,
        "charging_efficiency": 0.95,
        "forecast_when_absent": True,
        "weekday": {
            "car_available_from_hour": 18,
            "ready_by_hour": 7,
            "daily_rest_soc": 60.0,
        },
        "weekend": {
            "car_available_from_hour": 18,
            "ready_by_hour": 7,
            "daily_rest_soc": 30.0,
        },
    },
}


def test_generic_target_excludes_anchor_morning_partial_day():
    anchor = window_anchor_for_date(date(2025, 1, 1))
    slots = window_slot_datetimes(anchor)
    window_kwh = generic_flex_target_kwh_for_window(MEIN_HAUSHALT_GENERIC, slots, anchor)
    naive_kwh = sum(
        generic_daily_target_kwh_for_day(MEIN_HAUSHALT_GENERIC, day)
        for day in {slot.date() for slot in slots}
    )
    assert window_kwh == 6.0
    assert naive_kwh == 12.0


def test_planning_flex_daily_targets_infer_window_end_from_slots():
    anchor = datetime(2025, 1, 1, 7, 0)
    slots = window_slot_datetimes(anchor)
    profile = {"consumers": [MEIN_HAUSHALT_GENERIC]}
    flex = [{"id": "standard"}]
    targets = planning_flex_daily_targets(flex, profile, slots)
    assert targets["standard"] == 6.0


def test_planning_ev_target_uses_departure_day_only():
    anchor = datetime(2025, 1, 6, 7, 0)
    slots = window_slot_datetimes(anchor)
    profile = {"consumers": [EV_CONSUMER]}
    flex = [{"id": "ev"}]
    targets = planning_ev_daily_targets(flex, profile, slots, window_end=anchor)
    naive_kwh = sum(
        __import__("house_config.ev_profile", fromlist=["ev_daily_kwh"]).ev_daily_kwh(
            EV_CONSUMER, day
        )
        for day in {slot.date() for slot in slots}
    )
    assert targets["ev"] > 0.0
    assert targets["ev"] < naive_kwh
