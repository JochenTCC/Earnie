"""Tests for Live heat-storage floor planner (2.7.b)."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from optimizer.thermal_live_store import (
    build_heat_storage_observability,
    live_min_kwh_by_day,
    map_forced_hours_to_slot_indices,
    plan_live_store_horizon,
)
from optimizer.thermal_model import ThermalBand, capacity_kwh_per_k_from_volume


def _band() -> ThermalBand:
    return ThermalBand(setpoint_c=45.0, tolerance_c=5.0)


def test_plan_forces_wp_when_start_below_floor():
    band = _band()
    capacity = capacity_kwh_per_k_from_volume(500.0)
    plan = plan_live_store_horizon(
        start_temp_c=38.0,
        ambient_forecast_c=[0.0] * 6,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.02,
        wp_electric_kw=2.0,
        jaz=3.5,
        living_area_m2=0.0,
        persons=0,
    )
    assert any(plan.forced_hour_flags)
    assert plan.floor_electric_kwh > 0.0
    assert plan.start_temp_c == 38.0


def test_plan_opp_cap_when_below_setpoint_after_floor():
    band = _band()
    capacity = capacity_kwh_per_k_from_volume(800.0)
    plan = plan_live_store_horizon(
        start_temp_c=42.0,
        ambient_forecast_c=[15.0] * 4,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.005,
        wp_electric_kw=2.0,
        jaz=4.0,
        living_area_m2=0.0,
        persons=0,
    )
    # Start above floor (40): may not force; still headroom to setpoint 45.
    assert plan.opp_cap_electric_kwh > 0.0
    assert len(plan.store_temp_c) == 4
    assert len(plan.q_sim_kwh) == 4
    assert plan.q_sim_kwh[0] == pytest.approx(
        capacity * plan.store_temp_c[0]
    )


def test_plan_opp_cap_zero_at_setpoint():
    band = _band()
    capacity = capacity_kwh_per_k_from_volume(500.0)
    plan = plan_live_store_horizon(
        start_temp_c=45.0,
        ambient_forecast_c=[20.0] * 4,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.001,
        wp_electric_kw=2.0,
        jaz=4.0,
        living_area_m2=0.0,
        persons=0,
    )
    assert plan.opp_cap_electric_kwh == 0.0


def test_plan_t_low_forces_near_term_when_eq_ok():
    band = _band()
    capacity = capacity_kwh_per_k_from_volume(500.0)
    plan = plan_live_store_horizon(
        start_temp_c=42.0,
        ambient_forecast_c=[18.0] * 4,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.001,
        wp_electric_kw=2.0,
        jaz=4.0,
        temp_low_c=38.0,
        living_area_m2=0.0,
        persons=0,
        used_measured_low=True,
    )
    assert plan.forced_hour_flags[0] is True
    assert plan.floor_electric_kwh > 0.0


def test_plan_missing_t_low_skips_hint():
    band = _band()
    capacity = capacity_kwh_per_k_from_volume(500.0)
    warm = plan_live_store_horizon(
        start_temp_c=42.0,
        ambient_forecast_c=[18.0] * 4,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.001,
        wp_electric_kw=2.0,
        jaz=4.0,
        temp_low_c=None,
        living_area_m2=0.0,
        persons=0,
    )
    cold_bottom = plan_live_store_horizon(
        start_temp_c=42.0,
        ambient_forecast_c=[18.0] * 4,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.001,
        wp_electric_kw=2.0,
        jaz=4.0,
        temp_low_c=38.0,
        living_area_m2=0.0,
        persons=0,
    )
    assert warm.forced_hour_flags[0] is False or warm.floor_electric_kwh <= cold_bottom.floor_electric_kwh
    assert cold_bottom.forced_hour_flags[0] is True


def test_map_forced_hours_to_quarter_slots():
    day = date(2026, 1, 15)
    matrix = [
        {
            "date": day,
            "hour": 10,
            "slot_datetime": datetime(2026, 1, 15, 10, 0),
            "consumption_mode": "live_snapshot",
        },
        {
            "date": day,
            "hour": 10,
            "slot_datetime": datetime(2026, 1, 15, 10, 15),
            "consumption_mode": "live_snapshot",
        },
        {
            "date": day,
            "hour": 11,
            "slot_datetime": datetime(2026, 1, 15, 11, 0),
            "consumption_mode": "live_snapshot",
        },
        {
            "date": day,
            "hour": 11,
            "slot_datetime": datetime(2026, 1, 15, 11, 15),
            "consumption_mode": "live_snapshot",
        },
    ]
    # Force hour offset 0 only → first two QH (10:00 and 10:15)
    forced = map_forced_hours_to_slot_indices(matrix, [True, False])
    assert forced == [0, 1]


def test_live_min_kwh_adds_opp_on_first_day():
    day = date(2026, 1, 15)
    matrix = [
        {
            "date": day,
            "hour": 0,
            "slot_datetime": datetime(2026, 1, 15, 0, 0),
            "consumption_mode": "live_snapshot",
        },
    ]
    band = _band()
    capacity = capacity_kwh_per_k_from_volume(500.0)
    plan = plan_live_store_horizon(
        start_temp_c=42.0,
        ambient_forecast_c=[15.0] * 4,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.005,
        wp_electric_kw=2.0,
        jaz=4.0,
        living_area_m2=0.0,
        persons=0,
    )
    by_day = live_min_kwh_by_day(matrix, plan)
    assert plan.opp_cap_electric_kwh > 0.0
    assert by_day == {day: round(plan.opp_cap_electric_kwh, 3)}


def test_live_min_kwh_excludes_floor_when_above_setpoint():
    """Above setpoint: opp=0 and floor must not create a movable day budget."""
    day = date(2026, 1, 15)
    matrix = [
        {
            "date": day,
            "hour": hour,
            "slot_datetime": datetime(2026, 1, 15, hour, 0),
            "consumption_mode": "live_snapshot",
        }
        for hour in range(24)
    ]
    band = _band()
    capacity = capacity_kwh_per_k_from_volume(887.0)
    plan = plan_live_store_horizon(
        start_temp_c=60.0,
        ambient_forecast_c=[10.0] * 48,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.01,
        wp_electric_kw=1.9,
        jaz=4.0,
        living_area_m2=157.0,
        building_mass="mittel",
        annual_heat_kwh=6000.0,
        persons=2,
    )
    assert plan.opp_cap_electric_kwh == 0.0
    assert live_min_kwh_by_day(matrix, plan) == {}


def test_hot_store_floor_does_not_force_within_few_hours():
    """Regression Shadow 66 °C: short-forecast H must not empty the buffer by ~14:00."""
    band = ThermalBand(setpoint_c=47.0, tolerance_c=5.0)
    capacity = capacity_kwh_per_k_from_volume(887.0)
    # Cold short forecast would previously inflate H by ~8760/n and force WP in ~3 h.
    ambient = [8.0] * 8 + [14.0] * 16 + [8.0] * 24
    plan = plan_live_store_horizon(
        start_temp_c=66.6,
        ambient_forecast_c=ambient,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=0.01,
        wp_electric_kw=1.9,
        jaz=4.3,
        temp_low_c=56.1,
        living_area_m2=157.0,
        building_mass="mittel",
        target_temp_c=21.5,
        heating_limit_c=15.0,
        annual_heat_kwh=6280.0,
        persons=2,
        used_measured_eq=True,
        used_measured_low=True,
        house_profile=None,  # force short-forecast scale fallback
    )
    first = next((i for i, f in enumerate(plan.forced_hour_flags) if f), None)
    assert plan.opp_cap_electric_kwh == 0.0
    assert first is None or first >= 12
    assert plan.store_temp_c[3] > 52.0


@patch("optimizer.thermal_live_store.resolve_heat_storage_readings")
def test_build_heat_storage_observability_includes_q(mock_readings):
    from optimizer.thermal_live_store import HeatStorageReadings

    mock_readings.return_value = HeatStorageReadings(
        temp_eq_c=42.0,
        temp_low_c=38.0,
        used_measured_eq=True,
        used_measured_low=True,
    )
    consumer = {
        "id": "wp_heating",
        "type": "thermal_annual",
        "nominal_power_kw": 3.0,
        "thermal": {
            "living_area_m2": 0.0,
            "heat_storage": {
                "volume_liters": 500.0,
                "heat_loss_kw_per_k": 0.02,
                "setpoint_c": 45.0,
                "tolerance_c": 5.0,
            },
        },
    }
    item = build_heat_storage_observability(
        consumer,
        house_profile={"consumers": [consumer]},
        ambient_forecast_c=[10.0] * 4,
    )
    assert item is not None
    assert item["kind"] == "heat_storage"
    assert item["readings_c"]["temp_eq"] == 42.0
    capacity = capacity_kwh_per_k_from_volume(500.0)
    assert item["heat_content_kwh"]["q_meas"] == pytest.approx(
        round(capacity * 42.0, 3)
    )
    assert len(item["horizon_q_sim_kwh"]) == 4
