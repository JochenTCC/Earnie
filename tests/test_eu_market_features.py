"""Tests für EU-Markt-Features (Preis-Prognose Training)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from data.eu_market_features import (
    _public_power_hourly,
    _renewable_series_from_public_power,
    month_ranges,
    normalize_hour_slot,
)

VIENNA = ZoneInfo("Europe/Vienna")


def test_month_ranges_splits_calendar_months():
    ranges = month_ranges(
        datetime(2025, 6, 15).date(),
        datetime(2025, 8, 10).date(),
    )
    assert ranges == [
        (datetime(2025, 6, 15).date(), datetime(2025, 7, 1).date()),
        (datetime(2025, 7, 1).date(), datetime(2025, 8, 1).date()),
        (datetime(2025, 8, 1).date(), datetime(2025, 8, 10).date()),
    ]


def test_renewable_series_from_public_power_sums_wind_and_resamples_hourly():
    slot = datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA)
    payload = {
        "unix_seconds": [
            int(slot.timestamp()),
            int((slot.replace(minute=15)).timestamp()),
        ],
        "production_types": [
            {"name": "Wind onshore", "data": [1000.0, 2000.0]},
            {"name": "Wind offshore", "data": [500.0, 500.0]},
            {"name": "Solar", "data": [3000.0, 1000.0]},
            {"name": "Fossil gas", "data": [999.0, 999.0]},
        ],
    }

    frame = _renewable_series_from_public_power(payload)

    assert len(frame) == 1
    hour = normalize_hour_slot(slot)
    assert frame.loc[hour, "wind_mw"] == 2000.0
    assert frame.loc[hour, "solar_mw"] == 2000.0


def test_public_power_hourly_includes_load_and_residual():
    slot = datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA)
    payload = {
        "unix_seconds": [int(slot.timestamp())],
        "production_types": [
            {"name": "Wind onshore", "data": [1000.0]},
            {"name": "Solar", "data": [2000.0]},
            {"name": "Load", "data": [50000.0]},
            {"name": "Residual load", "data": [47000.0]},
        ],
    }
    frame = _public_power_hourly(payload)
    hour = normalize_hour_slot(slot)
    assert frame.loc[hour, "load_mw"] == 50000.0
    assert frame.loc[hour, "residual_load_mw"] == 47000.0


def test_normalize_hour_slot_strips_minutes():
    moment = datetime(2025, 7, 1, 10, 45, 30, tzinfo=VIENNA)
    assert normalize_hour_slot(moment) == datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA)
