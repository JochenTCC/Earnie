"""Tests für thermisches RC-Modell."""
from __future__ import annotations

import pytest

from optimizer.thermal_model import (
    ThermalBand,
    capacity_kwh_per_k_from_volume,
    compute_heat_loss_kw,
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


def test_compute_heat_loss_extra_path_against_fixed_reference():
    loss = compute_heat_loss_kw(
        36.0,
        10.0,
        heat_loss_kw_per_k=0.01,
        extra_paths=[{"heat_loss_kw_per_k": 0.005, "reference": "fixed", "reference_temp_c": 15.0}],
    )
    assert loss == pytest.approx(0.01 * 26.0 + 0.005 * 21.0)


def test_freezer_reference_band_below_ambient():
    band = ThermalBand(setpoint_c=-18.0, tolerance_c=2.0)
    assert band.max_c == -16.0
    capacity = capacity_kwh_per_k_from_volume(350)
    warmed = simulate_next_temp_c(
        -18.0,
        22.0,
        0.0,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.003,
        heating_efficiency=0.85,
    )
    assert warmed > -18.0
