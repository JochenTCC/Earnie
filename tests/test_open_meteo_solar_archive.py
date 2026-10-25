# tests/test_open_meteo_solar_archive.py
"""Tests für Open-Meteo Solar Archive PV in cons_data-Synthese."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
import requests

from data import open_meteo_solar_archive as archive


def test_irradiance_wm2_to_pv_kw_scales_with_kwp():
    assert archive.irradiance_wm2_to_pv_kw(500.0, 10.0) == pytest.approx(5.0)
    assert archive.irradiance_wm2_to_pv_kw(None, 10.0) == 0.0
    assert archive.irradiance_wm2_to_pv_kw(500.0, 0.0) == 0.0


def test_irradiance_wm2_to_thermal_kwh_scales_with_area_and_eta():
    assert archive.irradiance_wm2_to_thermal_kwh(1000.0, 8.0) == pytest.approx(3.2)
    assert archive.irradiance_wm2_to_thermal_kwh(1000.0, 8.0, eta=0.5) == pytest.approx(4.0)
    assert archive.irradiance_wm2_to_thermal_kwh(None, 8.0) == 0.0


def test_last_full_archive_year():
    assert archive.last_full_archive_year(reference=date(2026, 7, 13)) == 2025


def test_climate_bundle_pv_and_thermal_at_slot():
    surface = archive.TiltedSurface(tilt_deg=20.0, azimuth_deg=0.0)
    index = pd.DatetimeIndex([datetime(2024, 7, 13, 13, 0)])
    bundle = archive.OpenMeteoClimateBundle(
        temperature_c=pd.Series([22.0], index=index),
        tilted_wm2={surface: pd.Series([500.0], index=index)},
    )
    assert bundle.pv_kw_at(surface, 10.0, datetime(2024, 7, 13, 13, 0)) == pytest.approx(5.0)
    assert bundle.thermal_kwh_at(surface, 8.0, datetime(2024, 7, 13, 13, 0)) == pytest.approx(1.6)


def test_fetch_hourly_pv_kw_series_parses_archive_payload(monkeypatch):
    def _fake_get(url, params, timeout):
        assert url == archive.OPEN_METEO_ARCHIVE
        assert params["hourly"] == "global_tilted_irradiance"
        class Resp:
            status_code = 200
            url = archive.OPEN_METEO_ARCHIVE

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "hourly": {
                        "time": ["2024-07-13T07:00", "2024-07-13T11:00"],
                        "global_tilted_irradiance": [333.8, 666.8],
                    }
                }

        return Resp()

    monkeypatch.setattr(archive.requests, "get", _fake_get)
    series = archive.fetch_hourly_pv_kw_series(
        date(2024, 7, 13),
        date(2024, 7, 13),
        lat=48.0,
        lon=10.0,
        tilt=20.0,
        azimuth=-10.0,
        kwp=10.0,
        timezone="Europe/Berlin",
    )
    assert series[datetime(2024, 7, 13, 9, 0)] == pytest.approx(3.338)
    assert series[datetime(2024, 7, 13, 13, 0)] == pytest.approx(6.668)


def test_build_open_meteo_climate_bundle_parses_payload(monkeypatch):
    surface = archive.TiltedSurface(tilt_deg=20.0, azimuth_deg=-10.0)

    def _fake_get(url, params, timeout):
        hourly_var = params["hourly"]
        if hourly_var == archive.HOURLY_TEMP_VAR:
            payload = {
                "hourly": {
                    "time": ["2024-07-13T07:00", "2024-07-13T11:00"],
                    "temperature_2m": [18.0, 24.0],
                }
            }
        else:
            payload = {
                "hourly": {
                    "time": ["2024-07-13T07:00", "2024-07-13T11:00"],
                    "global_tilted_irradiance": [400.0, 800.0],
                }
            }
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        return Resp()

    monkeypatch.setattr(archive.requests, "get", _fake_get)
    bundle = archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        lat=48.0,
        lon=10.0,
        timezone="Europe/Berlin",
        surfaces=[surface],
    )
    dates, temps = bundle.daily_mean_temperatures()
    assert dates == [date(2024, 7, 13)]
    assert temps[0] == pytest.approx(21.0)
    assert bundle.pv_kw_at(surface, 10.0, datetime(2024, 7, 13, 13, 0)) == pytest.approx(8.0)


def test_archive_payload_is_requested_in_utc_and_converted_per_date():
    """One fixed offset per response is wrong: summer is UTC+2, winter UTC+1, DST days differ."""
    payload = {
        "hourly": {
            "time": [
                "2025-01-15T07:00",  # CET   -> 08:00
                "2025-07-15T07:00",  # CEST  -> 09:00
                "2025-10-26T00:00",  # CEST  -> 02:00 (first)
                "2025-10-26T01:00",  # CET   -> 02:00 (repeated hour, averaged)
                "2025-10-26T02:00",  # CET   -> 03:00
            ],
            "temperature_2m": [1.0, 2.0, 10.0, 20.0, 3.0],
        }
    }
    series = archive._hourly_series_from_payload(
        payload,
        hourly_vars="temperature_2m",
        start=date(2025, 1, 15),
        end=date(2025, 10, 27),
        timezone="Europe/Vienna",
    )["temperature_2m"]
    assert series[datetime(2025, 1, 15, 8)] == pytest.approx(1.0)
    assert series[datetime(2025, 7, 15, 9)] == pytest.approx(2.0)
    assert series[datetime(2025, 10, 26, 2)] == pytest.approx(15.0)
    assert series[datetime(2025, 10, 26, 3)] == pytest.approx(3.0)
    assert not series.index.has_duplicates


def test_fetch_chunk_requests_utc_and_one_day_earlier(monkeypatch):
    seen = {}

    def _fake_get(url, params, timeout):
        seen.update(params)
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = (
            b'{"hourly":{"time":["2025-06-30T23:00","2025-07-01T00:00"],'
            b'"temperature_2m":[1.0,2.0]}}'
        )
        return response

    monkeypatch.setattr(archive.requests, "get", _fake_get)
    payload = archive._fetch_hourly_archive_chunk(
        lat=48.0,
        lon=10.0,
        timezone="Europe/Vienna",
        start=date(2025, 7, 1),
        end=date(2025, 7, 2),
        hourly_vars=archive.HOURLY_TEMP_VAR,
    )
    assert seen["timezone"] == "UTC"
    assert seen["start_date"] == "2025-06-30"
    assert seen["end_date"] == "2025-07-01"
    # 23:00 UTC = 01:00 local on 07-01 stays, nothing before 07-01 00:00 local survives
    series = payload[archive.HOURLY_TEMP_VAR]
    assert list(series.index) == [pd.Timestamp("2025-07-01 01:00"), pd.Timestamp("2025-07-01 02:00")]


def test_build_open_meteo_climate_bundle_raises_on_api_error(monkeypatch):
    def _fake_get(url, params, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(archive.requests, "get", _fake_get)
    monkeypatch.setattr(archive.time, "sleep", lambda *_args, **_kwargs: None)
    with pytest.raises(requests.ConnectionError, match="offline"):
        archive.build_open_meteo_climate_bundle(
            date(2024, 7, 13),
            date(2024, 7, 13),
            lat=48.0,
            lon=10.0,
            timezone="Europe/Berlin",
            surfaces=[archive.TiltedSurface(20.0, 0.0)],
            use_cache=False,
        )


def test_fetch_hourly_archive_chunk_retries_502(monkeypatch):
    calls = {"n": 0}

    def _fake_get(url, params, timeout):
        calls["n"] += 1
        response = requests.Response()
        response.status_code = 502 if calls["n"] < 3 else 200
        response.url = url
        response._content = (
            b'{"hourly":{"time":["2024-07-13T00:00"],"temperature_2m":[21.0]}}'
            if response.status_code == 200
            else b"bad gateway"
        )
        return response

    monkeypatch.setattr(archive.requests, "get", _fake_get)
    monkeypatch.setattr(archive.time, "sleep", lambda *_args, **_kwargs: None)
    payload = archive._fetch_hourly_archive_chunk(
        lat=48.0,
        lon=10.0,
        timezone="Europe/Berlin",
        start=date(2024, 7, 13),
        end=date(2024, 7, 14),
        hourly_vars=archive.HOURLY_TEMP_VAR,
    )
    assert calls["n"] == 3
    assert list(payload[archive.HOURLY_TEMP_VAR]) == [21.0]


def test_open_meteo_cache_roundtrip(monkeypatch, tmp_path):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    archive.clear_open_meteo_bundle_mem_cache()
    install_open_meteo_climate_mock(monkeypatch)
    surface = archive.TiltedSurface(tilt_deg=20.0, azimuth_deg=0.0)
    kwargs = {
        "lat": 48.0,
        "lon": 10.0,
        "timezone": "Europe/Berlin",
        "surfaces": [surface],
        "cache_dir": tmp_path,
    }
    first = archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    call_count = {"n": 0}
    original = archive._fetch_hourly_archive_chunk

    def _counting_fetch(*args, **fetch_kwargs):
        call_count["n"] += 1
        return original(*args, **fetch_kwargs)

    monkeypatch.setattr(archive, "_fetch_hourly_archive_chunk", _counting_fetch)
    second = archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    assert call_count["n"] == 0
    assert len(first.temperature_c) == len(second.temperature_c)


def test_open_meteo_mem_cache_skips_read_json(monkeypatch, tmp_path):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    archive.clear_open_meteo_bundle_mem_cache()
    install_open_meteo_climate_mock(monkeypatch)
    surface = archive.TiltedSurface(tilt_deg=20.0, azimuth_deg=0.0)
    kwargs = {
        "lat": 48.0,
        "lon": 10.0,
        "timezone": "Europe/Berlin",
        "surfaces": [surface],
        "cache_dir": tmp_path,
    }
    archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    archive.clear_open_meteo_bundle_mem_cache()
    read_count = {"n": 0}
    original_read = archive.pd.read_json

    def _counting_read(*args, **kwargs):
        read_count["n"] += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(archive.pd, "read_json", _counting_read)
    archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    assert read_count["n"] == 1
    archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    assert read_count["n"] == 1


def test_open_meteo_mem_cache_invalidates_on_mtime(monkeypatch, tmp_path):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    archive.clear_open_meteo_bundle_mem_cache()
    install_open_meteo_climate_mock(monkeypatch)
    surface = archive.TiltedSurface(tilt_deg=20.0, azimuth_deg=0.0)
    kwargs = {
        "lat": 48.0,
        "lon": 10.0,
        "timezone": "Europe/Berlin",
        "surfaces": [surface],
        "cache_dir": tmp_path,
    }
    archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    path = archive.open_meteo_cache_path(
        48.0,
        10.0,
        "Europe/Berlin",
        date(2024, 7, 13),
        date(2024, 7, 13),
        [surface],
        cache_dir=tmp_path,
    )
    read_count = {"n": 0}
    original_read = archive.pd.read_json

    def _counting_read(*args, **kwargs):
        read_count["n"] += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(archive.pd, "read_json", _counting_read)
    archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    assert read_count["n"] == 0
    # Bump mtime without changing content so mem-cache must re-read.
    new_mtime = path.stat().st_mtime + 2.0
    import os

    os.utime(path, (new_mtime, new_mtime))
    archive.build_open_meteo_climate_bundle(
        date(2024, 7, 13),
        date(2024, 7, 13),
        **kwargs,
    )
    assert read_count["n"] == 1


def test_open_meteo_cache_read_failure_raises(tmp_path):
    archive.clear_open_meteo_bundle_mem_cache()
    surface = archive.TiltedSurface(tilt_deg=20.0, azimuth_deg=0.0)
    path = archive.open_meteo_cache_path(
        48.0,
        10.0,
        "Europe/Berlin",
        date(2024, 7, 13),
        date(2024, 7, 13),
        [surface],
        cache_dir=tmp_path,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="cache unlesbar"):
        archive.build_open_meteo_climate_bundle(
            date(2024, 7, 13),
            date(2024, 7, 13),
            lat=48.0,
            lon=10.0,
            timezone="Europe/Berlin",
            surfaces=[surface],
            cache_dir=tmp_path,
        )


def test_fetch_budget_stops_retries_instead_of_sleeping(monkeypatch):
    calls: list[float] = []

    def failing_get(url, params=None, timeout=None):
        calls.append(timeout)
        raise requests.ConnectionError("down")

    def no_sleep(seconds):
        raise AssertionError(f"must not sleep {seconds}s past the budget")

    monkeypatch.setattr(archive.requests, "get", failing_get)
    monkeypatch.setattr(archive.time, "sleep", no_sleep)
    with archive.climate_fetch_budget(1.0):
        with pytest.raises(archive.ClimateFetchBudgetExceeded, match="down"):
            archive._archive_http_get({"latitude": 47.4})
    assert len(calls) == 1
    assert calls[0] <= 1.0


def test_fetch_without_budget_keeps_retrying(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(
        archive.requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    monkeypatch.setattr(archive.time, "sleep", sleeps.append)
    with pytest.raises(requests.ConnectionError):
        archive._archive_http_get({"latitude": 47.4})
    assert sleeps == [2.0, 4.0, 8.0, 16.0, 32.0]
