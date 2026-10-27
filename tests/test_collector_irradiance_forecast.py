"""ThermalHorizon P3 — collector irradiance from the Open-Meteo forecast."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from data import outdoor_forecast as of
from data.open_meteo_solar_archive import irradiance_wm2_to_thermal_kwh
from optimizer import thermal_live_store as tls

_NOW = datetime(2026, 10, 15, 10, 0, 0)


@pytest.fixture(autouse=True)
def _clear_forecast_caches():
    of._CACHE.clear()
    of._TILTED_CACHE.clear()
    yield
    of._CACHE.clear()
    of._TILTED_CACHE.clear()


def _series(start: datetime, hours: int, value) -> list[tuple[datetime, float]]:
    return [(start + timedelta(hours=offset), value(offset)) for offset in range(hours)]


def _fake_fetch(calls: list):
    def _fetch(lat, lon, *, forecast_days, hourly_vars, extra_params=None):
        calls.append(
            {
                "lat": lat,
                "lon": lon,
                "forecast_days": forecast_days,
                "hourly_vars": hourly_vars,
                "extra_params": extra_params,
            }
        )
        day0 = _NOW.replace(hour=0)
        return {
            of.HOURLY_TEMP_VAR: _series(day0, 72, lambda h: 5.0 + h * 0.1),
            of.HOURLY_TILTED_VAR: _series(day0, 72, lambda h: float(100 * (h % 24))),
        }

    return _fetch


def test_tilted_forecast_one_request_rounds_surface_and_seeds_temperature(monkeypatch):
    calls: list = []
    monkeypatch.setattr(of, "_fetch_open_meteo_hourly_vars", _fake_fetch(calls))
    with patch.object(of, "datetime") as mock_dt:
        mock_dt.now.return_value = _NOW
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        wm2 = of.get_hourly_tilted_irradiance_forecast_wm2(
            horizon=6,
            tilt_deg=18.4,
            azimuth_deg=27.6,
            latitude=47.4,
            longitude=9.7,
            start=_NOW,
        )
        with patch.object(of, "_fetch_open_meteo_hourly") as temp_fetch:
            temps = of.get_hourly_outdoor_forecast_c(
                horizon=6, latitude=47.4, longitude=9.7, start=_NOW
            )

    assert wm2 == [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0]
    assert len(calls) == 1
    assert calls[0]["hourly_vars"] == (of.HOURLY_TEMP_VAR, of.HOURLY_TILTED_VAR)
    assert calls[0]["extra_params"] == {"tilt": 18, "azimuth": 28}
    temp_fetch.assert_not_called()
    assert temps[0] == 6.0


def test_fetch_vars_rejects_missing_irradiance(monkeypatch):
    payload = {
        "hourly": {
            "time": ["2026-10-15T10:00", "2026-10-15T11:00"],
            "temperature_2m": [5.0, 6.0],
            "global_tilted_irradiance": [120.0, None],
        }
    }
    monkeypatch.setattr(of, "_shadow_transport", lambda *_a: of._ReplayedResponse(payload))
    with pytest.raises(ValueError, match="global_tilted_irradiance"):
        of._fetch_open_meteo_hourly_vars(
            47.4,
            9.7,
            forecast_days=2,
            hourly_vars=(of.HOURLY_TEMP_VAR, of.HOURLY_TILTED_VAR),
        )


def _thermal(area: float = 10.3) -> dict:
    return {
        "solar_thermal_area_m2": area,
        "solar_thermal_tilt_deg": 18.0,
        "solar_thermal_azimuth_deg": 28.0,
    }


_PROFILE = {"latitude": 47.4, "longitude": 9.7}


def test_collector_solar_from_forecast(monkeypatch):
    seen: dict = {}

    def _forecast(**kwargs):
        seen.update(kwargs)
        return [0.0, 400.0, 800.0]

    monkeypatch.setattr(of, "get_hourly_tilted_irradiance_forecast_wm2", _forecast)
    solar, source = tls.resolve_live_collector_solar_kw(
        _thermal(), _PROFILE, 3, start=_NOW
    )

    assert source == tls.SOLAR_SOURCE_FORECAST
    assert solar == [
        round(irradiance_wm2_to_thermal_kwh(value, 10.3), 6) for value in (0.0, 400.0, 800.0)
    ]
    assert (seen["tilt_deg"], seen["azimuth_deg"]) == (18.0, 28.0)
    assert (seen["latitude"], seen["longitude"], seen["horizon"]) == (47.4, 9.7, 3)


def test_collector_solar_falls_back_to_archive_year_with_warning(monkeypatch, caplog):
    def _fail(**_kwargs):
        raise ValueError("HTTP 503")

    monkeypatch.setattr(of, "get_hourly_tilted_irradiance_forecast_wm2", _fail)
    monkeypatch.setattr(
        tls, "_archive_year_collector_solar_kw", lambda *_a, **_k: [0.1, 0.2, 0.3]
    )
    with caplog.at_level(logging.WARNING, logger=tls.logger.name):
        solar, source = tls.resolve_live_collector_solar_kw(
            _thermal(), _PROFILE, 3, start=_NOW
        )

    assert (solar, source) == ([0.1, 0.2, 0.3], tls.SOLAR_SOURCE_ARCHIVE_FALLBACK)
    assert "Vorjahreswerte" in caplog.text


def test_collector_solar_without_collector_area():
    solar, source = tls.resolve_live_collector_solar_kw(_thermal(0.0), _PROFILE, 4)

    assert (solar, source) == ([0.0] * 4, tls.SOLAR_SOURCE_NONE)


@patch("optimizer.thermal_live_store.resolve_heat_storage_readings")
def test_observability_reports_collector_source(mock_readings, monkeypatch):
    mock_readings.return_value = tls.HeatStorageReadings(
        temp_eq_c=44.0, temp_low_c=None, used_measured_eq=True, used_measured_low=False
    )
    monkeypatch.setattr(
        tls,
        "resolve_live_collector_solar_kw",
        lambda *_a, **_k: ([0.0] * 4, tls.SOLAR_SOURCE_ARCHIVE_FALLBACK),
    )
    consumer = {
        "id": "wp",
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "thermal": {
            "living_area_m2": 0.0,
            "solar_thermal_area_m2": 10.3,
            "heat_storage": {
                "volume_liters": 887.0,
                "heat_loss_kw_per_k": 0.01,
                "setpoint_c": 47.0,
                "tolerance_c": 5.0,
            },
        },
    }
    item = tls.build_heat_storage_observability(
        consumer, house_profile=_PROFILE, ambient_forecast_c=[8.0] * 4
    )

    assert item["collector_solar_source"] == tls.SOLAR_SOURCE_ARCHIVE_FALLBACK
