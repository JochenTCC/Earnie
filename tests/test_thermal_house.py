"""Thermals P2 — house indoor RC unit tests."""
from __future__ import annotations

from optimizer.thermal_house import (
    calibrate_house_heat_loss_kw_per_k,
    house_capacity_kwh_per_k,
    house_requests_heat,
    house_year_result,
    normalize_building_mass,
    step_house_hour,
)


def test_building_mass_capacity_mittel_140m2():
    assert normalize_building_mass("MITTEL") == "mittel"
    assert house_capacity_kwh_per_k(140.0, "mittel") == 12.6
    assert house_capacity_kwh_per_k(140.0, "leicht") == 7.0
    assert house_capacity_kwh_per_k(140.0, "schwer") == 18.2


def test_heavier_bauweise_cools_slower():
    ambient = 0.0
    h = 0.1
    start = 21.0
    light = start
    heavy = start
    c_light = house_capacity_kwh_per_k(120.0, "leicht")
    c_heavy = house_capacity_kwh_per_k(120.0, "schwer")
    for _ in range(24):
        light = step_house_hour(
            light, ambient, heat_in_kw=0.0, capacity_kwh_per_k=c_light, heat_loss_kw_per_k=h
        )
        heavy = step_house_hour(
            heavy, ambient, heat_in_kw=0.0, capacity_kwh_per_k=c_heavy, heat_loss_kw_per_k=h
        )
    assert light < heavy < start


def test_house_requests_heat_when_cold():
    c = house_capacity_kwh_per_k(100.0, "mittel")
    assert house_requests_heat(
        20.0,
        -5.0,
        capacity_kwh_per_k=c,
        heat_loss_kw_per_k=0.15,
        band_min_c=20.5,
    )


def test_calibrate_h_from_ambient():
    ambient = [0.0] * 100 + [20.0] * 100
    h = calibrate_house_heat_loss_kw_per_k(
        2100.0,
        ambient,
        target_temp_c=21.0,
        heating_limit_c=15.0,
    )
    # 100 h × (21-0) = 2100 → H = 1.0
    assert h == 1.0


def test_house_year_winter_keeps_band_without_store():
    temps = [-5.0] * 14
    radiation = [1.0] * 14
    result = house_year_result(
        living_area_m2=120.0,
        building_class=3,
        heat_pump_type="luft",
        persons=2,
        latitude=48.2,
        longitude=11.0,
        target_temp_c=21.0,
        heating_limit_c=15.0,
        hp_electric_kw=4.0,
        heat_storage=None,
        daily_temps=temps,
        daily_radiation_mj=radiation,
        building_mass="mittel",
        house_tolerance_c=0.5,
        # Short winter-only series would over-calibrate H; fix envelope like EAW order.
        house_heat_loss_kw_per_k=0.12,
    )
    assert len(result.hourly_house_temp_c) == 14 * 24
    assert not result.hourly_store_temp_c
    assert sum(result.daily_electric_kwh) > 0.0
    assert min(result.hourly_house_temp_c) >= 19.0
    assert max(result.hourly_house_temp_c) <= 24.0


def test_house_year_with_store_returns_both_temps():
    temps = [5.0] * 10
    radiation = [5.0] * 10
    result = house_year_result(
        living_area_m2=100.0,
        building_class=3,
        heat_pump_type="luft",
        persons=2,
        latitude=48.2,
        longitude=11.0,
        target_temp_c=21.0,
        heating_limit_c=15.0,
        hp_electric_kw=3.0,
        heat_storage={
            "volume_liters": 800.0,
            "heat_loss_kw_per_k": 0.02,
            "setpoint_c": 45.0,
            "tolerance_c": 5.0,
        },
        daily_temps=temps,
        daily_radiation_mj=radiation,
        solar_thermal_area_m2=0.0,
    )
    assert len(result.hourly_house_temp_c) == len(result.hourly_store_temp_c)
    assert len(result.hourly_store_temp_c) == 10 * 24
