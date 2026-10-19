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


def test_from_scenario_sums_multiple_pv_systems():
    profile = _profile()
    surface_a = TiltedSurface(tilt_deg=20.0, azimuth_deg=0.0)
    surface_b = TiltedSurface(tilt_deg=30.0, azimuth_deg=-90.0)
    slot = datetime(2024, 7, 13, 13, 0)
    bundle = OpenMeteoClimateBundle(
        temperature_c=pd.Series([22.0], index=pd.DatetimeIndex([slot])),
        tilted_wm2={
            surface_a: pd.Series([800.0], index=pd.DatetimeIndex([slot])),
            surface_b: pd.Series([400.0], index=pd.DatetimeIndex([slot])),
        },
    )
    scenario = {
        "_house_profile": profile,
        "_planning_pv_systems": [
            {
                "id": "a",
                "label": "Süd",
                "pv_kwp": 10.0,
                "pv_tilt": 20.0,
                "pv_azimuth": 0.0,
            },
            {
                "id": "b",
                "label": "Ost",
                "pv_kwp": 5.0,
                "pv_tilt": 30.0,
                "pv_azimuth": -90.0,
            },
        ],
    }
    climate = ModeledClimateContext.from_scenario(scenario)
    climate.seed_year_bundle(2024, bundle)
    assert climate.pv_kwp == 15.0
    assert climate.pv_kw_at(slot) == pytest.approx(10.0)  # 8 + 2
    by_system = climate.pv_kw_by_system_for_slots([slot])
    assert by_system["a"][0] == pytest.approx(8.0)
    assert by_system["b"][0] == pytest.approx(2.0)


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
        "heat_storage": {
            "volume_liters": 800.0,
            "heat_loss_kw_per_k": 0.02,
            "setpoint_c": 45.0,
            "tolerance_c": 5.0,
        },
    }
    without, year = thermal_annual_kwh_from_archive(thermal, reference_year=2024)
    with_solar, _ = thermal_annual_kwh_from_archive(
        {**thermal, "solar_thermal_area_m2": 8.0},
        reference_year=2024,
    )
    assert year == 2024
    assert without > 0.0
    assert with_solar < without


def test_strip_assets_reference_has_no_zero_kwp_pv_surface():
    from house_config.entity_resolution import strip_assets_for_reference

    profile = _profile()
    profile["consumers"][0]["solar_thermal_area_m2"] = 6.0
    profile["consumers"][0]["solar_thermal_tilt_deg"] = 18.0
    profile["consumers"][0]["solar_thermal_azimuth_deg"] = 26.0
    live = {
        "pv_kwp": 10.0,
        "pv_tilt": 18.0,
        "pv_azimuth": -154.0,
        "_house_profile": profile,
        "_planning_pv_systems": [
            {
                "id": "roof",
                "label": "roof",
                "pv_kwp": 10.0,
                "pv_tilt": 18.0,
                "pv_azimuth": -154.0,
            }
        ],
    }
    ref = strip_assets_for_reference(live)
    climate = ModeledClimateContext.from_scenario(ref)
    assert climate.pv_systems == []
    from data.modeled_climate import _surfaces_for_profile

    surfaces = _surfaces_for_profile(profile, climate._pv_surfaces())
    assert [(s.tilt_deg, s.azimuth_deg) for s in surfaces] == [(18.0, 26.0)]


def _seasonal_bundle(year: int, hours: int):
    """Synthetic seasonal temperature series (same weather for equal day-of-year)."""
    import numpy as np
    import pandas as pd

    from data.open_meteo_solar_archive import OpenMeteoClimateBundle

    index = pd.date_range(f"{year}-01-01", periods=hours, freq="h")
    day = np.arange(8760)[:hours] / 24.0
    temps = 9.0 - 11.0 * np.cos(2 * np.pi * day / 365.0)
    return OpenMeteoClimateBundle(
        temperature_c=pd.Series(temps, index=index, dtype=float),
        tilted_wm2={},
    )


def _heat_pump_consumer() -> dict:
    return {
        "id": "waermepumpe",
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "latitude": 47.4,
        "longitude": 9.7,
        "timezone_name": "Europe/Vienna",
        "living_area_m2": 150.0,
        "building_class": 2,
        "heat_pump_type": "erde",
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "hwb_kwh_m2": 40.0,
    }


def _month_kwh(climate, consumer: dict, year: int, month: int) -> float:
    from datetime import datetime, timedelta

    total = 0.0
    day = datetime(year, month, 1)
    while day.month == month:
        for hour in range(24):
            total += climate.thermal_consumer_kw_at(consumer, day.replace(hour=hour))
        day += timedelta(days=1)
    return total


def _climate_with_full_and_truncated_year():
    from data.modeled_climate import ModeledClimateContext

    climate = ModeledClimateContext(lat=47.4, lon=9.7, timezone="Europe/Vienna")
    climate.seed_year_bundle(2025, _seasonal_bundle(2025, 8760))
    climate.seed_year_bundle(2026, _seasonal_bundle(2026, 6984))  # ends 18 Oct
    return climate


def test_heat_pump_profile_of_incomplete_year_is_not_recalibrated(monkeypatch):
    """Same weather + fixed envelope H => same demand, also in a truncated (current) year.

    Regression: H was calibrated per bundle, so a year ending in October squeezed the
    whole annual heat demand into fewer days (+50 % in winter months).
    """
    from data.modeled_climate import ModeledClimateContext

    monkeypatch.setattr(
        ModeledClimateContext, "_reference_house_heat_loss", lambda self, c, t: 0.25
    )
    climate = _climate_with_full_and_truncated_year()
    consumer = _heat_pump_consumer()
    for month in (1, 2, 3):
        assert _month_kwh(climate, consumer, 2026, month) == pytest.approx(
            _month_kwh(climate, consumer, 2025, month), rel=0.02
        )
    assert _month_kwh(climate, consumer, 2025, 1) > 50.0  # heating actually happens


def test_per_bundle_calibration_inflates_incomplete_year(monkeypatch):
    """Negative control: without a fixed H the truncated year is visibly inflated."""
    from data.modeled_climate import ModeledClimateContext

    monkeypatch.setattr(
        ModeledClimateContext, "_reference_house_heat_loss", lambda self, c, t: None
    )
    climate = _climate_with_full_and_truncated_year()
    consumer = _heat_pump_consumer()
    full = _month_kwh(climate, consumer, 2025, 1)
    truncated = _month_kwh(climate, consumer, 2026, 1)
    assert truncated > full * 1.10


def test_reference_house_heat_loss_comes_from_thermal_parameters(monkeypatch):
    from data.modeled_climate import ModeledClimateContext
    from optimizer import thermal_parameters as tp
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    tp.THERMAL_PARAMETERS_CACHE.clear() if hasattr(tp, "THERMAL_PARAMETERS_CACHE") else None
    climate = ModeledClimateContext(lat=47.4, lon=9.7, timezone="Europe/Vienna")
    consumer = _heat_pump_consumer()
    h = climate._reference_house_heat_loss(consumer, consumer)
    assert h is not None and h > 0.0
    direct = tp.house_thermal_parameters(consumer).house_heat_loss_kw_per_k
    assert h == pytest.approx(direct)
