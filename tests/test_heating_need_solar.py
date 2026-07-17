"""Tests für Solarthermie und Geo im Heizbedarfsmodell."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from data.heating_need import (
    daily_electric_kwh,
    estimate_annual_kwh,
    heating_params_from_thermal,
    weekly_electric_kwh,
)
from house_config.baseload import consumer_annual_kwh
from house_config.profiles_store import (
    load_house_profiles_document,
    save_house_profiles_document,
)


def _base_thermal() -> dict:
    return {
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
        "latitude": 48.2,
        "longitude": 11.0,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
    }


def test_weekly_electric_kwh_without_solar_regression():
    params = heating_params_from_thermal(_base_thermal())
    weekly = weekly_electric_kwh(**params)
    assert len(weekly) == 52
    assert sum(weekly) > 0


def test_solar_thermal_reduces_annual_wp_demand():
    base = _base_thermal()
    without = estimate_annual_kwh(**heating_params_from_thermal(base))
    with_solar = estimate_annual_kwh(
        **heating_params_from_thermal(
            {
                **base,
                "solar_thermal_area_m2": 8.0,
                "solar_thermal_tilt_deg": 18.0,
                "solar_thermal_azimuth_deg": 0.0,
            }
        )
    )
    assert with_solar < without


def test_daily_electric_kwh_hourly_collector_reduces_summer_day():
    idx = pd.date_range("2024-07-13 00:00", periods=24, freq="h")
    hourly_temp = pd.Series([20.0] * 24, index=idx)
    hourly_wm2 = pd.Series([600.0] * 24, index=idx)
    params = heating_params_from_thermal(
        {
            **_base_thermal(),
            "solar_thermal_area_m2": 8.0,
            "solar_thermal_tilt_deg": 18.0,
            "solar_thermal_azimuth_deg": 0.0,
        }
    )
    without_params = {**params, "solar_thermal_area_m2": 0.0}
    without = daily_electric_kwh(
        **without_params,
        hourly_temperature_c=hourly_temp,
        hourly_collector_wm2=pd.Series(0.0, index=idx),
    )
    with_collector = daily_electric_kwh(
        **params,
        hourly_temperature_c=hourly_temp,
        hourly_collector_wm2=hourly_wm2,
    )
    assert with_collector[0] < without[0]


def test_consumer_annual_kwh_reflects_solar_thermal(monkeypatch):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    without = consumer_annual_kwh(
        {
            "type": "thermal_annual",
            "latitude": 48.2,
            "longitude": 11.0,
            "living_area_m2": 120.0,
            "building_class": 3,
            "heat_pump_type": "luft",
            "persons": 2,
        }
    )
    with_solar = consumer_annual_kwh(
        {
            "type": "thermal_annual",
            "latitude": 48.2,
            "longitude": 11.0,
            "living_area_m2": 120.0,
            "building_class": 3,
            "heat_pump_type": "luft",
            "persons": 2,
            "solar_thermal_area_m2": 6.0,
        }
    )
    assert with_solar < without


def test_profiles_store_geo_and_solar_roundtrip(tmp_path: Path):
    path = tmp_path / "house_profiles.json"
    doc = {
        "profiles": [
            {
                "id": "geo_solar",
                "label": "Geo Solar",
                "annual_kwh": 5000.0,
                "latitude": 47.4,
                "longitude": 9.7,
                "default_pv_tilt": 30.0,
                "default_pv_azimuth": -10.0,
                "consumers": [
                    {
                        "id": "wp",
                        "label": "WP",
                        "type": "thermal_annual",
                        "nominal_power_kw": 3.0,
                        "living_area_m2": 100.0,
                        "building_class": 3,
                        "heat_pump_type": "luft",
                        "persons": 2,
                        "solar_thermal_area_m2": 4.0,
                        "solar_thermal_tilt_deg": 20.0,
                        "solar_thermal_azimuth_deg": 5.0,
                    }
                ],
            }
        ]
    }
    save_house_profiles_document(str(path), doc)
    raw = json.loads(path.read_text(encoding="utf-8"))
    profile = raw["profiles"][0]
    assert profile["latitude"] == 47.4
    assert profile["longitude"] == 9.7
    assert profile["default_pv_tilt"] == 30.0
    assert profile["default_pv_azimuth"] == -10.0
    consumer = profile["consumers"][0]
    assert consumer["solar_thermal_area_m2"] == 4.0

    loaded = load_house_profiles_document(str(path))["profiles"]["geo_solar"]
    thermal = loaded["consumers"][0]["thermal"]
    assert thermal["latitude"] == 47.4
    assert thermal["solar_thermal_area_m2"] == 4.0


def test_profiles_store_requires_geo_for_thermal(tmp_path: Path):
    path = tmp_path / "house_profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "missing_geo",
                        "label": "Ohne Geo",
                        "annual_kwh": 4000.0,
                        "consumers": [
                            {
                                "id": "wp",
                                "type": "thermal_annual",
                                "living_area_m2": 100.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="latitude und longitude"):
        load_house_profiles_document(str(path))


def test_climate_fixture_has_radiation():
    from data.heating_need import load_climate_daily

    temps, radiation = load_climate_daily(lat=48.2, lon=11.0)
    assert len(temps) >= 364
    assert len(radiation) >= 364


def test_climate_fixture_resolves_committed_path(tmp_path, monkeypatch):
    """Docker/CI has no data/cache/; committed data/fixtures/ must still load."""
    from data import heating_need

    cache = tmp_path / "cache" / "heating_climate_default.json"
    fixtures = Path("data/fixtures/heating_climate_default.json")
    assert fixtures.is_file()
    monkeypatch.setattr(
        heating_need,
        "_CLIMATE_CACHE_CANDIDATES",
        (cache, fixtures),
    )
    temps, radiation = heating_need.load_climate_daily()
    assert len(temps) >= 364
    assert len(radiation) >= 364
