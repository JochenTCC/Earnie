"""Tests für thermisches RC-Modell."""
from __future__ import annotations

from optimizer.thermal_model import (
    ThermalBand,
    capacity_kwh_per_k_from_volume,
    plan_minimum_heating,
    simulate_next_temp_c,
)


def test_capacity_from_6000_liters():
    capacity = capacity_kwh_per_k_from_volume(6000)
    assert 6.9 < capacity < 7.1


def test_simulate_heating_raises_temp():
    next_temp = simulate_next_temp_c(
        35.0,
        10.0,
        2.8,
        capacity_kwh_per_k=7.0,
        heat_loss_kw_per_k=0.01,
        heating_efficiency=0.95,
    )
    assert next_temp > 35.0


def test_plan_minimum_heating_cold_night_needs_energy():
    band = ThermalBand(setpoint_c=36.5, tolerance_c=1.0)
    ambients = [5.0] * 24
    plan = plan_minimum_heating(
        start_temp_c=36.0,
        ambient_forecast_c=ambients,
        band=band,
        heat_power_kw=2.8,
        capacity_kwh_per_k=7.0,
        heat_loss_kw_per_k=0.01,
        heating_efficiency=0.95,
    )
    assert plan.required_kwh > 0
    assert plan.heating_hours >= 1


def test_plan_warm_day_less_than_cold_day():
    band = ThermalBand(setpoint_c=36.5, tolerance_c=1.0)
    warm = plan_minimum_heating(
        start_temp_c=36.5,
        ambient_forecast_c=[25.0] * 24,
        band=band,
        heat_power_kw=2.8,
        capacity_kwh_per_k=7.0,
        heat_loss_kw_per_k=0.01,
        heating_efficiency=0.95,
    )
    cold = plan_minimum_heating(
        start_temp_c=36.5,
        ambient_forecast_c=[0.0] * 24,
        band=band,
        heat_power_kw=2.8,
        capacity_kwh_per_k=7.0,
        heat_loss_kw_per_k=0.01,
        heating_efficiency=0.95,
    )
    assert warm.required_kwh <= cold.required_kwh
