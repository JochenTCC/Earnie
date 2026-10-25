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


def test_month_ranges_rejects_empty_span():
    with pytest.raises(ValueError, match="end muss nach start"):
        month_ranges(date(2025, 7, 1), date(2025, 7, 1))


def test_normalize_hour_slot_naive_gets_planning_tz():
    with patch("data.eu_market_features.config.get_planning_timezone", return_value="Europe/Vienna"):
        out = normalize_hour_slot(datetime(2025, 7, 1, 10, 45))
    assert out == datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA)


def test_http_get_json_retries_on_429_then_succeeds():
    from data import eu_market_features as emf

    bad = type("R", (), {"status_code": 429, "raise_for_status": lambda self: None})()
    good_payload = {"ok": True}
    good = type(
        "R",
        (),
        {
            "status_code": 200,
            "raise_for_status": lambda self: None,
            "json": lambda self: good_payload,
        },
    )()
    with patch.object(emf, "API_PAUSE_SECONDS", 0):
        with patch.object(emf, "API_RETRY_BASE_SECONDS", 0):
            with patch.object(emf.time, "sleep", return_value=None):
                with patch.object(emf.config, "get_global_timeout", return_value=5):
                    with patch.object(emf.requests, "get", side_effect=[bad, good]):
                        assert emf._http_get_json("https://example.test", {}) == good_payload


def test_dedupe_hourly_mean_averages_duplicates():
    from data.eu_market_features import _dedupe_hourly_mean

    idx = pd.DatetimeIndex(
        [datetime(2025, 7, 1, 10, tzinfo=VIENNA), datetime(2025, 7, 1, 10, tzinfo=VIENNA)]
    )
    series = pd.Series([10.0, 30.0], index=idx)
    out = _dedupe_hourly_mean(series)
    assert float(out.iloc[0]) == pytest.approx(20.0)


def test_fetch_country_power_hourly_uses_month_chunks():
    from data import eu_market_features as emf

    start = date(2025, 6, 15)
    end = date(2025, 7, 10)
    hour = datetime(2025, 6, 15, 12, tzinfo=VIENNA)
    stub = pd.DataFrame(
        {"wind_mw": [1.0], "solar_mw": [2.0], "load_mw": [3.0], "residual_load_mw": [4.0]},
        index=pd.DatetimeIndex([hour], name="slot_datetime"),
    )
    with patch.object(emf, "API_PAUSE_SECONDS", 0):
        with patch.object(
            emf, "_http_get_json", return_value={"unix_seconds": [], "production_types": []}
        ):
            with patch.object(emf, "_public_power_hourly", return_value=stub):
                frame = emf.fetch_country_power_hourly("at", start, end)
    assert not frame.empty
    assert list(frame.columns) == ["wind_mw", "solar_mw", "load_mw", "residual_load_mw"]


def test_fetch_country_renewables_hourly_wrapper():
    from data import eu_market_features as emf

    hour = datetime(2025, 7, 1, 12, tzinfo=VIENNA)
    stub = pd.DataFrame(
        {"wind_mw": [1.0], "solar_mw": [2.0], "load_mw": [3.0], "residual_load_mw": [4.0]},
        index=pd.DatetimeIndex([hour], name="slot_datetime"),
    )
    with patch.object(emf, "fetch_country_power_hourly", return_value=stub):
        out = emf.fetch_country_renewables_hourly("at", date(2025, 7, 1), date(2025, 7, 2))
    assert list(out.columns) == ["wind_mw", "solar_mw"]


def test_fetch_at_day_ahead_hourly_parses_price():
    from data import eu_market_features as emf

    slot = datetime(2025, 7, 1, 10, tzinfo=VIENNA)
    payload = {
        "unix_seconds": [int(slot.timestamp())],
        "price": [150.0],  # EUR/MWh → 15.0 ct/kWh
    }
    with patch.object(emf, "_http_get_json", return_value=payload):
        with patch.object(emf, "API_PAUSE_SECONDS", 0):
            series = emf.fetch_at_day_ahead_hourly(date(2025, 7, 1), date(2025, 7, 2))
    assert float(series.iloc[0]) == pytest.approx(15.0)


def test_weighted_eu_weather_from_points():
    from data.eu_market_features import WEATHER_GRID, _weighted_eu_weather_from_points

    hour = datetime(2025, 7, 1, 12, tzinfo=VIENNA)
    point_frames = {
        point.name: pd.DataFrame(
            {"wind_speed_kmh": [10.0], "shortwave_radiation_wm2": [100.0]},
            index=pd.DatetimeIndex([hour]),
        )
        for point in WEATHER_GRID
    }
    out = _weighted_eu_weather_from_points(point_frames)
    assert float(out["eu_wind_speed_kmh"].iloc[0]) == pytest.approx(10.0)
    assert float(out["eu_shortwave_radiation_wm2"].iloc[0]) == pytest.approx(100.0)


def test_hourly_frame_from_open_meteo_payload():
    from data.eu_market_features import _hourly_frame_from_open_meteo_payload

    payload = {
        "hourly": {
            "time": ["2025-07-01T10:00", "2025-07-01T11:00"],
            "wind_speed_10m": [5.0, 6.0],
            "shortwave_radiation": [100.0, 200.0],
        }
    }
    with patch("data.eu_market_features.config.get_planning_timezone", return_value="Europe/Vienna"):
        frame = _hourly_frame_from_open_meteo_payload(payload)
    assert len(frame) == 2
    assert float(frame.iloc[1]["shortwave_radiation_wm2"]) == pytest.approx(200.0)


def test_forecast_days_for_range_clamped():
    from data import eu_market_features as emf

    today = date(2025, 7, 1)
    real_datetime = emf.datetime

    class _FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2025, 7, 1, 12, tzinfo=tz or VIENNA)

    with patch.object(emf, "datetime", _FixedDateTime):
        days = emf._forecast_days_for_range(today, today + timedelta(days=40))
    assert days == 16


def test_remap_power_by_hour_of_day():
    from data.eu_market_features import remap_power_by_hour_of_day

    archive = pd.DataFrame(
        {"eu_wind_mw": [10.0, 20.0]},
        index=pd.DatetimeIndex(
            [datetime(2024, 1, 1, 10, tzinfo=VIENNA), datetime(2024, 1, 1, 11, tzinfo=VIENNA)]
        ),
    )
    targets = [datetime(2025, 7, 1, 10, tzinfo=VIENNA), datetime(2025, 7, 1, 11, tzinfo=VIENNA)]
    out = remap_power_by_hour_of_day(archive, targets)
    assert float(out.iloc[0]["eu_wind_mw"]) == pytest.approx(10.0)
    assert float(out.iloc[1]["eu_wind_mw"]) == pytest.approx(20.0)


def test_remap_power_by_hour_of_day_empty_raises():
    from data.eu_market_features import remap_power_by_hour_of_day

    with pytest.raises(ValueError, match="leeres"):
        remap_power_by_hour_of_day(pd.DataFrame(), [datetime(2025, 7, 1, 10, tzinfo=VIENNA)])


def test_build_training_dataset_joins(monkeypatch):
    from data import eu_market_features as emf

    hour = datetime(2025, 7, 1, 12, tzinfo=VIENNA)
    prices = pd.Series([12.0], index=pd.DatetimeIndex([hour]), name="price_epex_cent_kwh")
    power = pd.DataFrame(
        {
            "eu_wind_mw": [1.0],
            "eu_solar_mw": [2.0],
            "eu_load_mw": [3.0],
            "eu_residual_load_mw": [4.0],
        },
        index=pd.DatetimeIndex([hour]),
    )
    weather = pd.DataFrame(
        {"eu_wind_speed_kmh": [5.0], "eu_shortwave_radiation_wm2": [6.0]},
        index=pd.DatetimeIndex([hour]),
    )
    monkeypatch.setattr(emf, "fetch_at_day_ahead_hourly", lambda *_a: prices)
    monkeypatch.setattr(emf, "fetch_eu_power_hourly", lambda *_a: power)
    monkeypatch.setattr(emf, "fetch_eu_weather_hourly", lambda *_a: weather)
    frame = emf.build_training_dataset(date(2025, 7, 1), date(2025, 7, 2))
    assert "hour" in frame.columns
    assert float(frame.iloc[0]["price_epex_cent_kwh"]) == pytest.approx(12.0)


def test_enrich_dataset_with_eu_load(monkeypatch):
    from data import eu_market_features as emf

    hour = datetime(2025, 7, 1, 12, tzinfo=VIENNA)
    base = pd.DataFrame({"price_epex_cent_kwh": [1.0]}, index=pd.DatetimeIndex([hour]))
    power = pd.DataFrame(
        {"eu_load_mw": [10.0], "eu_residual_load_mw": [8.0]},
        index=pd.DatetimeIndex([hour]),
    )
    monkeypatch.setattr(emf, "fetch_eu_power_hourly", lambda *_a: power)
    out = emf.enrich_dataset_with_eu_load(base)
    assert float(out.iloc[0]["eu_load_mw"]) == pytest.approx(10.0)


def test_default_training_range_length():
    from data.eu_market_features import default_training_range

    start, end = default_training_range()
    assert (end - start).days == 365


def test_http_get_json_connection_error_is_not_retried():
    """An unreachable host fails at the first attempt (2.6.2 behaviour), no 5x backoff."""
    import requests

    from data import eu_market_features as emf

    with patch.object(emf.time, "sleep") as sleep_mock:
        with patch.object(emf.config, "get_global_timeout", return_value=5):
            with patch.object(
                emf.requests, "get", side_effect=requests.ConnectTimeout("no route")
            ) as get_mock:
                with pytest.raises(emf.ApiUnreachableError, match="nicht erreichbar"):
                    emf._http_get_json("https://example.test/x", {})

    assert get_mock.call_count == 1
    sleep_mock.assert_not_called()


def test_fetch_eu_power_hourly_aborts_at_first_unreachable_country():
    """12 countries x full retry loop kept the daemon busy for 12+ min (issue #59)."""
    from data import eu_market_features as emf

    start = date(2025, 7, 1)
    with patch.object(
        emf,
        "fetch_country_power_hourly",
        side_effect=emf.ApiUnreachableError("nicht erreichbar"),
    ) as country_mock:
        with pytest.raises(emf.ApiUnreachableError):
            fetch_eu_power_hourly(start, start + timedelta(days=1))

    assert country_mock.call_count == 1


def test_fetch_eu_power_hourly_unreachable_host_makes_one_request_in_total():
    import requests

    from data import eu_market_features as emf

    start = date(2025, 7, 1)
    with patch.object(emf.time, "sleep"):
        with patch.object(emf.config, "get_global_timeout", return_value=5):
            with patch.object(
                emf.requests, "get", side_effect=requests.ConnectionError("down")
            ) as get_mock:
                with pytest.raises(emf.ApiUnreachableError):
                    fetch_eu_power_hourly(start, start + timedelta(days=1))

    assert get_mock.call_count == 1


def test_open_meteo_archive_month_requests_utc_and_converts_to_planning_tz():
    import data.eu_market_features as emf

    seen: dict = {}

    def _fake_get_json(url, params):
        seen.update(params)
        return {
            "hourly": {
                "time": ["2025-06-30T22:00", "2025-06-30T23:00", "2025-12-31T22:00", "2025-12-31T23:00"],
                "wind_speed_10m": [1.0, 2.0, 3.0, 4.0],
                "shortwave_radiation": [0.0, 0.0, 0.0, 0.0],
            }
        }

    point = emf.WEATHER_GRID[0]
    with patch.object(emf, "_http_get_json", _fake_get_json), patch.object(
        emf.config, "get_planning_timezone", return_value="Europe/Vienna"
    ):
        frame = emf._fetch_open_meteo_archive_month(point, date(2025, 7, 1), date(2025, 12, 31))
    assert seen["timezone"] == "UTC"
    assert seen["start_date"] == "2025-06-30"
    # 22:00 UTC on 06-30 = 00:00 CEST on 07-01; 22:00 UTC on 12-31 is past the chunk end
    assert [ts.hour for ts in frame.index] == [0, 1]
    assert list(frame["wind_speed_kmh"]) == [1.0, 2.0]
