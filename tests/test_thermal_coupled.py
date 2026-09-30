"""Thermals P2 — coupled heat-storage unit and regression tests."""
from __future__ import annotations

import pandas as pd

from data.heating_need import daily_electric_kwh, heating_params_from_thermal
from optimizer.thermal_coupled import (
    HEAT_STORAGE_ABS_MAX_C,
    capacity_kwh_per_k_from_volume,
    heat_storage_enabled,
    normalize_heat_storage,
    step_coupled_hour,
)
from optimizer.thermal_model import ThermalBand


def _storage(**overrides) -> dict:
    base = {
        "volume_liters": 800.0,
        "heat_loss_kw_per_k": 0.02,
        "setpoint_c": 45.0,
        "tolerance_c": 5.0,
    }
    base.update(overrides)
    return base


def test_normalize_heat_storage_disabled_when_volume_zero():
    assert normalize_heat_storage({"volume_liters": 0}) is None
    assert not heat_storage_enabled(None)
    assert not heat_storage_enabled({"volume_liters": 0})


def test_step_solar_raises_store_temp():
    band = ThermalBand(45.0, 5.0)
    capacity = capacity_kwh_per_k_from_volume(800.0)
    start = 40.0
    result = step_coupled_hour(
        start,
        ambient_c=10.0,
        solar_kw=5.0,
        demand_kw=0.0,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.02,
        band=band,
        wp_electric_kw=3.0,
        jaz=3.5,
    )
    assert result.temp_c > start
    assert not result.wp_on
    assert result.electric_kwh == 0.0


def test_step_demand_and_loss_trigger_wp():
    band = ThermalBand(45.0, 5.0)
    capacity = capacity_kwh_per_k_from_volume(500.0)
    result = step_coupled_hour(
        40.0,
        ambient_c=0.0,
        solar_kw=0.0,
        demand_kw=8.0,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.05,
        band=band,
        wp_electric_kw=3.0,
        jaz=3.5,
    )
    assert result.wp_on
    assert result.electric_kwh == 3.0


def test_step_wp_capped_at_setpoint_not_set_plus_tol():
    """WP may fill toward setpoint; end T from WP alone must not exceed setpoint."""
    band = ThermalBand(45.0, 5.0)
    capacity = capacity_kwh_per_k_from_volume(200.0)
    result = step_coupled_hour(
        39.0,
        ambient_c=10.0,
        solar_kw=0.0,
        demand_kw=0.0,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.0,
        band=band,
        wp_electric_kw=10.0,
        jaz=4.0,
    )
    assert result.wp_on
    assert result.temp_c <= band.setpoint_c + 1e-6
    assert result.temp_c > band.min_c


def test_step_solar_may_exceed_setpoint_up_to_abs_max():
    """Above setpoint, WP stays off; strong solar may raise T past setpoint toward 95 °C."""
    band = ThermalBand(45.0, 5.0)
    capacity = capacity_kwh_per_k_from_volume(300.0)
    result = step_coupled_hour(
        46.0,
        ambient_c=20.0,
        solar_kw=40.0,
        demand_kw=0.0,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.0,
        band=band,
        wp_electric_kw=5.0,
        jaz=3.5,
    )
    assert not result.wp_on
    assert result.electric_kwh == 0.0
    assert result.temp_c > band.setpoint_c
    assert result.temp_c <= HEAT_STORAGE_ABS_MAX_C + 1e-6


def test_step_solar_capped_at_abs_max():
    band = ThermalBand(45.0, 5.0)
    capacity = capacity_kwh_per_k_from_volume(100.0)
    result = step_coupled_hour(
        90.0,
        ambient_c=25.0,
        solar_kw=100.0,
        demand_kw=0.0,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.0,
        band=band,
        wp_electric_kw=0.0,
        jaz=3.5,
    )
    assert result.temp_c <= HEAT_STORAGE_ABS_MAX_C + 1e-6
    assert result.solar_kwh < 100.0


def test_step_wp_forced_below_min():
    band = ThermalBand(45.0, 5.0)
    capacity = capacity_kwh_per_k_from_volume(800.0)
    result = step_coupled_hour(
        40.5,
        ambient_c=5.0,
        solar_kw=0.0,
        demand_kw=2.0,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.02,
        band=band,
        wp_electric_kw=3.0,
        jaz=3.5,
    )
    assert result.wp_on
    assert result.electric_kwh > 0.0
    assert result.temp_c <= band.setpoint_c + 1e-6


def test_no_storage_uses_house_rc_not_legacy_open_loop():
    """Without heat_storage, living_area > 0 uses house RC (not HDD open-loop)."""
    params = heating_params_from_thermal(
        {
            "living_area_m2": 120.0,
            "building_class": 3,
            "heat_pump_type": "luft",
            "persons": 2,
            "latitude": 48.2,
            "longitude": 11.0,
            "target_temp_c": 21.5,
            "heating_limit_c": 15.0,
            "solar_thermal_area_m2": 0.0,
            "building_mass": "mittel",
        }
    )
    assert "heat_storage" not in params
    daily = daily_electric_kwh(**params)
    assert len(daily) >= 364
    assert sum(daily) > 0


def test_coupled_solar_reduces_summer_wp_vs_no_solar():
    storage = _storage()
    base = {
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
        "latitude": 48.2,
        "longitude": 11.0,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "heat_storage": storage,
        "hp_electric_kw": 3.0,
    }
    # Mid-summer-like short series: warm ambient, low heating demand
    temps = [22.0] * 365
    radiation = [20.0] * 365  # MJ/m² roughly sunny
    without_solar = daily_electric_kwh(
        **{**base, "solar_thermal_area_m2": 0.0},
        daily_temps=temps,
        daily_radiation_mj=radiation,
    )
    with_solar = daily_electric_kwh(
        **{**base, "solar_thermal_area_m2": 12.0},
        daily_temps=temps,
        daily_radiation_mj=radiation,
    )
    assert sum(with_solar) < sum(without_solar)


def test_coupled_winter_demand_needs_wp():
    storage = _storage(volume_liters=400.0)
    temps = [-5.0] * 365
    radiation = [2.0] * 365
    daily = daily_electric_kwh(
        living_area_m2=120.0,
        building_class=3,
        heat_pump_type="luft",
        persons=2,
        latitude=48.2,
        longitude=11.0,
        target_temp_c=21.5,
        heating_limit_c=15.0,
        heat_storage=storage,
        hp_electric_kw=3.0,
        solar_thermal_area_m2=0.0,
        daily_temps=temps,
        daily_radiation_mj=radiation,
    )
    assert sum(daily) > 100.0


def test_coupled_hourly_climate_path():
    idx = pd.date_range("2024-01-15 00:00", periods=48, freq="h")
    hourly_temp = pd.Series([-2.0] * 48, index=idx)
    hourly_wm2 = pd.Series([0.0] * 48, index=idx)
    daily = daily_electric_kwh(
        living_area_m2=100.0,
        building_class=3,
        heat_pump_type="luft",
        persons=2,
        latitude=48.2,
        longitude=11.0,
        target_temp_c=21.5,
        heating_limit_c=15.0,
        heat_storage=_storage(),
        hp_electric_kw=4.0,
        solar_thermal_area_m2=0.0,
        hourly_temperature_c=hourly_temp,
        hourly_collector_wm2=hourly_wm2,
    )
    assert len(daily) == 2
    assert daily[0] > 0.0


def test_coupled_hourly_store_temps_match_day_count():
    from optimizer.thermal_coupled import coupled_hourly_store_temp_c, coupled_year_result

    idx = pd.date_range("2024-01-15 00:00", periods=48, freq="h")
    hourly_temp = pd.Series([-2.0] * 48, index=idx)
    kwargs = dict(
        living_area_m2=100.0,
        building_class=3,
        heat_pump_type="luft",
        persons=2,
        latitude=48.2,
        longitude=11.0,
        target_temp_c=21.5,
        heating_limit_c=15.0,
        heat_storage=_storage(),
        hp_electric_kw=4.0,
        solar_thermal_area_m2=0.0,
        hourly_temperature_c=hourly_temp,
        hourly_collector_wm2=pd.Series([0.0] * 48, index=idx),
        house_heat_loss_kw_per_k=0.12,
    )
    result = coupled_year_result(**kwargs)
    assert len(result.daily_electric_kwh) == 2
    assert len(result.hourly_store_temp_c) == 48
    assert len(result.hourly_house_temp_c) == 48
    assert coupled_hourly_store_temp_c(**kwargs) == result.hourly_store_temp_c
    assert min(result.hourly_store_temp_c) >= 39.0
    # No solar: WP ceiling is setpoint (not setpoint+tol); store stays near band floor/setpoint
    assert max(result.hourly_store_temp_c) <= 45.0 + 1e-6


def test_coupled_hourly_solar_can_raise_store_above_setpoint():
    from optimizer.thermal_coupled import coupled_year_result

    idx = pd.date_range("2024-07-01 00:00", periods=24, freq="h")
    hourly_temp = pd.Series([25.0] * 24, index=idx)
    # Strong midday irradiance on a large collector → store above setpoint
    wm2 = [0.0] * 24
    for h in range(10, 16):
        wm2[h] = 800.0
    result = coupled_year_result(
        living_area_m2=100.0,
        building_class=3,
        heat_pump_type="luft",
        persons=2,
        latitude=48.2,
        longitude=11.0,
        target_temp_c=21.5,
        heating_limit_c=15.0,
        heat_storage=_storage(volume_liters=300.0),
        hp_electric_kw=3.0,
        solar_thermal_area_m2=12.0,
        hourly_temperature_c=hourly_temp,
        hourly_collector_wm2=pd.Series(wm2, index=idx),
        house_heat_loss_kw_per_k=0.12,
    )
    assert max(result.hourly_store_temp_c) > 45.0
    assert max(result.hourly_store_temp_c) <= HEAT_STORAGE_ABS_MAX_C + 1e-6


def test_profiles_normalize_heat_storage():
    from house_config.profiles_thermal_annual import normalize_thermal_annual_consumer

    spec: dict = {}
    normalize_thermal_annual_consumer(
        {
            "living_area_m2": 100.0,
            "building_class": 2,
            "heat_storage": _storage(volume_liters=1000.0),
        },
        spec,
        copy_loxone_binding=lambda _r, _s: None,
    )
    assert spec["thermal"]["heat_storage"]["volume_liters"] == 1000.0
