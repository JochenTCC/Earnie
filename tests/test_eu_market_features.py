"""Tests für EU-Markt-Features (Preis-Prognose Training)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.eu_market_features import (
    GENERATION_COUNTRIES,
    _energy_charts_timeout_sec,
    _public_power_hourly,
    _renewable_series_from_public_power,
    fetch_eu_power_hourly,
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


def _stub_country_power(country: str, start: date, end: date) -> pd.DataFrame:
    del end
    hour = datetime(start.year, start.month, start.day, 12, tzinfo=VIENNA)
    return pd.DataFrame(
        {
            "wind_mw": [100.0],
            "solar_mw": [200.0],
            "load_mw": [1000.0],
            "residual_load_mw": [700.0],
        },
        index=pd.DatetimeIndex([hour], name="slot_datetime"),
    )


def test_fetch_eu_power_hourly_skips_failed_country():
    """One flaky Energy-Charts country must not abort the EU sum (NAS regression)."""

    def _fetch(country: str, start: date, end: date) -> pd.DataFrame:
        if country == "it":
            raise RuntimeError("API-Abruf fehlgeschlagen (timeout)")
        return _stub_country_power(country, start, end)

    start = date(2025, 7, 1)
    with patch(
        "data.eu_market_features.fetch_country_power_hourly",
        side_effect=_fetch,
    ):
        frame = fetch_eu_power_hourly(start, start + timedelta(days=1))

    assert not frame.empty
    assert "eu_wind_mw" in frame.columns
    # 11 successful countries × 100 MW wind (Italy skipped)
    assert float(frame["eu_wind_mw"].iloc[0]) == pytest.approx(
        100.0 * (len(GENERATION_COUNTRIES) - 1)
    )


def test_fetch_eu_power_hourly_raises_when_all_countries_fail():
    start = date(2025, 7, 1)
    with patch(
        "data.eu_market_features.fetch_country_power_hourly",
        side_effect=ValueError("Energy-Charts public_power: unix_seconds fehlt."),
    ):
        with pytest.raises(ValueError, match="alle Länder fehlgeschlagen"):
            fetch_eu_power_hourly(start, start + timedelta(days=1))


def test_energy_charts_timeout_floors_at_30():
    with patch("data.eu_market_features.config.get_global_timeout", return_value=5):
        assert _energy_charts_timeout_sec() == pytest.approx(30.0)
    with patch("data.eu_market_features.config.get_global_timeout", return_value=60):
        assert _energy_charts_timeout_sec() == pytest.approx(60.0)
