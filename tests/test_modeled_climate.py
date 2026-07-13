# tests/test_modeled_climate.py
"""Tests für ModeledClimateContext (Step 2)."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from data.modeled_climate import ModeledClimateContext
from data.open_meteo_solar_archive import OpenMeteoClimateBundle, TiltedSurface


def _profile() -> dict:
    return {
        "id": "test",
        "latitude": 48.0,
        "longitude": 10.0,
        "default_pv_tilt": 20.0,
        "default_pv_azimuth": 0.0,
        "consumers": [
            {
                "id": "haus",
                "type": "thermal_annual",
                "nominal_power_kw": 2.0,
                "living_area_m2": 120.0,
                "building_class": 3,
                "heat_pump_type": "luft",
                "persons": 2,
                "solar_thermal_area_m2": 0.0,
            }
        ],
    }


def test_pv_kw_at_uses_seeded_bundle():
    surface = TiltedSurface(tilt_deg=20.0, azimuth_deg=0.0)
    slot = datetime(2024, 7, 13, 13, 0)
    bundle = OpenMeteoClimateBundle(
        temperature_c=pd.Series([22.0], index=pd.DatetimeIndex([slot])),
        tilted_wm2={surface: pd.Series([800.0], index=pd.DatetimeIndex([slot]))},
    )
    climate = ModeledClimateContext.for_house_profile(_profile(), kwp=10.0)
    climate.seed_year_bundle(2024, bundle)
    assert climate.pv_kw_at(slot) == pytest.approx(8.0)


def test_from_scenario_overrides_pv_tilt():
    profile = _profile()
    scenario = {
        "_house_profile": profile,
        "pv_kwp": 6.0,
        "pv_tilt": 35.0,
        "pv_azimuth": -15.0,
        "latitude": 47.5,
        "longitude": 9.8,
    }
    climate = ModeledClimateContext.from_scenario(scenario)
    assert climate.pv_kwp == 6.0
    assert climate.pv_surface.tilt_deg == 35.0
    assert climate.pv_surface.azimuth_deg == -15.0
    assert climate.lat == 47.5


def test_thermal_annual_kwh_from_archive(monkeypatch):
    from data.modeled_climate import thermal_annual_kwh_from_archive
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    thermal = {
        "latitude": 48.0,
        "longitude": 10.0,
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
    }
    without, year = thermal_annual_kwh_from_archive(thermal, reference_year=2024)
    with_solar, _ = thermal_annual_kwh_from_archive(
        {**thermal, "solar_thermal_area_m2": 8.0},
        reference_year=2024,
    )
    assert year == 2024
    assert without > 0.0
    assert with_solar < without
