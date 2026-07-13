# tests/test_open_meteo_solar_archive.py
"""Tests für Open-Meteo Solar Archive PV in cons_data-Synthese."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
import requests

from data import open_meteo_solar_archive as archive


def _fallback(hour: int, month: int, kwp: float) -> float:
    return round(kwp * 0.01 * hour, 3)


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


def test_open_meteo_pv_lookup_uses_series_and_fallback():
    series = pd.Series(
        {datetime(2024, 7, 13, 13, 0): 6.5},
        dtype=float,
    )
    lookup = archive.OpenMeteoPvLookup(series, kwp=10.0, fallback=_fallback)
    assert lookup.kw_at(datetime(2024, 7, 13, 13, 0)) == pytest.approx(6.5)
    assert lookup.kw_at(datetime(2024, 7, 14, 13, 0)) == pytest.approx(1.3)


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
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "hourly": {
                        "time": ["2024-07-13T09:00", "2024-07-13T13:00"],
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
                    "time": ["2024-07-13T09:00", "2024-07-13T13:00"],
                    "temperature_2m": [18.0, 24.0],
                }
            }
        else:
            payload = {
                "hourly": {
                    "time": ["2024-07-13T09:00", "2024-07-13T13:00"],
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


def test_build_open_meteo_climate_bundle_raises_on_api_error(monkeypatch):
    def _fake_get(url, params, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(archive.requests, "get", _fake_get)
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


def test_open_meteo_cache_roundtrip(monkeypatch, tmp_path):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

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


def test_open_meteo_cache_read_failure_raises(tmp_path):
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


def test_build_open_meteo_pv_lookup_falls_back_on_api_error(monkeypatch):
    monkeypatch.setattr(
        archive,
        "_resolve_installation_params",
        lambda: (48.0, 10.0, 20.0, -10.0, 10.0, "Europe/Berlin"),
    )
    monkeypatch.setattr(
        archive,
        "fetch_hourly_pv_kw_series",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    lookup = archive.build_open_meteo_pv_lookup(
        date(2024, 7, 13),
        date(2024, 7, 13),
        fallback=_fallback,
    )
    assert lookup.kw_at(datetime(2024, 7, 13, 10, 0)) == pytest.approx(1.0)
