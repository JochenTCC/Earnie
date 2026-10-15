"""ThermalHorizon P1 — parameters from one reference-year simulation."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from optimizer.thermal_live_store import (
    HeatStorageReadings,
    plan_live_store_for_thermal_consumer,
    plan_live_store_horizon,
)
from optimizer.thermal_model import ThermalBand, capacity_kwh_per_k_from_volume
from optimizer.thermal_parameters import (
    SOURCE_OVERRIDE,
    SOURCE_YEAR_SIM,
    house_thermal_parameters,
    thermal_rc_parameters,
)
from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock


def _thermal(**overrides) -> dict:
    thermal = {
        "latitude": 48.0,
        "longitude": 10.0,
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
        "nominal_power_kw": 2.0,
        "heat_storage": {
            "volume_liters": 800.0,
            "heat_loss_kw_per_k": 0.02,
            "setpoint_c": 45.0,
            "tolerance_c": 5.0,
        },
    }
    thermal.update(overrides)
    return thermal


def test_house_parameters_match_year_sim_annual(monkeypatch):
    from data.modeled_climate import thermal_annual_kwh_from_archive

    install_open_meteo_climate_mock(monkeypatch)
    params = house_thermal_parameters(_thermal(), reference_year=2024)
    annual, year = thermal_annual_kwh_from_archive(_thermal(), reference_year=2024)

    assert params.reference_year == year == 2024
    assert params.annual_electric_kwh == annual
    assert params.house_heat_loss_kw_per_k > 0.0
    assert params.house_heat_loss_source == SOURCE_YEAR_SIM


def test_house_parameters_override_h(monkeypatch):
    install_open_meteo_climate_mock(monkeypatch)
    params = house_thermal_parameters(
        _thermal(house_heat_loss_kw_per_k=0.15), reference_year=2024
    )

    assert params.house_heat_loss_kw_per_k == 0.15
    assert params.house_heat_loss_source == SOURCE_OVERRIDE


def test_house_parameters_without_living_area_have_no_h(monkeypatch):
    install_open_meteo_climate_mock(monkeypatch)
    params = house_thermal_parameters(_thermal(living_area_m2=0.0), reference_year=2024)

    assert params.house_heat_loss_kw_per_k is None
    assert params.annual_electric_kwh > 0.0


def test_house_parameters_memoized_one_climate_load(monkeypatch):
    import data.modeled_climate as modeled_climate

    install_open_meteo_climate_mock(monkeypatch)
    calls = {"n": 0}
    original = modeled_climate.build_open_meteo_climate_bundle_for_year

    def _count(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(modeled_climate, "build_open_meteo_climate_bundle_for_year", _count)
    first = house_thermal_parameters(_thermal(), reference_year=2024)
    second = house_thermal_parameters(_thermal(), reference_year=2024)

    assert second == first
    assert calls["n"] == 1


def test_house_parameters_geo_from_profile_and_missing_geo_fails(monkeypatch):
    install_open_meteo_climate_mock(monkeypatch)
    no_geo = {k: v for k, v in _thermal().items() if k not in ("latitude", "longitude")}

    from_profile = house_thermal_parameters(
        no_geo,
        house_profile={"latitude": 48.0, "longitude": 10.0},
        reference_year=2024,
    )
    assert from_profile.annual_electric_kwh == house_thermal_parameters(
        _thermal(), reference_year=2024
    ).annual_electric_kwh
    with pytest.raises(ValueError, match="latitude"):
        house_thermal_parameters(no_geo, house_profile={}, reference_year=2024)


def test_thermal_rc_parameters_match_estimate(monkeypatch):
    from house_config.thermal_rc_profile import estimate_thermal_rc_annual_kwh

    install_open_meteo_climate_mock(monkeypatch)
    consumer = {
        "id": "pool",
        "type": "thermal_rc",
        "nominal_power_kw": 3.0,
        "thermal_rc": {
            "latitude": 48.0,
            "longitude": 10.0,
            "timezone_name": "Europe/Vienna",
            "setpoint_c": 36.0,
            "tolerance_c": 1.0,
            "water_volume_liters": 1500.0,
            "heat_loss_kw_per_k": 0.05,
            "heating_efficiency": 1.0,
        },
    }
    params = thermal_rc_parameters(consumer, reference_year=2024)
    annual, year = estimate_thermal_rc_annual_kwh(consumer, reference_year=2024)

    assert (params.annual_electric_kwh, params.reference_year) == (annual, year)
    assert params.house_heat_loss_kw_per_k is None


def test_live_store_plan_with_living_area_requires_h():
    with pytest.raises(ValueError, match="house_heat_loss_kw_per_k"):
        plan_live_store_horizon(
            start_temp_c=45.0,
            ambient_forecast_c=[5.0] * 4,
            band=ThermalBand(45.0, 5.0),
            capacity_kwh_per_k=capacity_kwh_per_k_from_volume(800.0),
            heat_loss_kw_per_k=0.02,
            wp_electric_kw=2.0,
            jaz=3.5,
            living_area_m2=120.0,
        )


@patch("optimizer.thermal_live_store.resolve_heat_storage_readings")
def test_live_store_plan_uses_parameter_h(mock_readings, monkeypatch):
    mock_readings.return_value = HeatStorageReadings(
        temp_eq_c=44.0, temp_low_c=None, used_measured_eq=True, used_measured_low=False
    )
    seen: dict = {}

    def _fake_params(thermal, *, house_profile=None, reference_year=None):
        from optimizer.thermal_parameters import ThermalParameters

        seen["thermal"] = thermal
        seen["house_profile"] = house_profile
        return ThermalParameters(2025, 3000.0, 0.11, SOURCE_YEAR_SIM)

    monkeypatch.setattr(
        "optimizer.thermal_parameters.house_thermal_parameters", _fake_params
    )
    thermal = {k: v for k, v in _thermal().items() if k != "nominal_power_kw"}
    consumer = {"id": "wp", "type": "thermal_annual", "nominal_power_kw": 1.9, "thermal": thermal}
    profile = {"latitude": 48.0, "longitude": 10.0, "consumers": [consumer]}

    with_h = plan_live_store_for_thermal_consumer(
        consumer,
        house_profile=profile,
        ambient_forecast_c=[0.0] * 6,
        solar_forecast_kw=[0.0] * 6,
    )

    assert with_h is not None
    assert seen["house_profile"] is profile
    # Same parameter key as baseload: consumer-level WP kW copied onto thermal.
    assert seen["thermal"]["nominal_power_kw"] == 1.9
