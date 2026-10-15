"""ThermalHorizon P4 — house-only horizon plan for Live without heat storage."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

from optimizer import thermal_live_store as tls
from optimizer.live_cycle_scope import live_cycle_scope
from optimizer.thermal_parameters import SOURCE_OVERRIDE, ThermalParameters

_DAY = date(2026, 1, 15)
_H = 0.12


def _source(**thermal_overrides) -> dict:
    thermal = {
        "living_area_m2": 157.0,
        "building_class": 2,
        "heat_pump_type": "erde",
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "house_tolerance_c": 0.5,
        "building_mass": "leicht",
        "house_heat_loss_kw_per_k": _H,
    }
    thermal.update(thermal_overrides)
    return {
        "id": "wp_heating",
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "daily_target_source": "thermal_annual",
        "thermal": thermal,
    }


_PROFILE = {"latitude": 47.4, "longitude": 9.7, "absent_mode": False}


@pytest.fixture
def fixed_h(monkeypatch):
    monkeypatch.setattr(
        "optimizer.thermal_parameters.house_thermal_parameters",
        lambda *_a, **_k: ThermalParameters(2025, 3000.0, _H, SOURCE_OVERRIDE),
    )


def test_house_horizon_matches_year_sim_day(fixed_h):
    """Same hourly rules as the year sim: equal weather → equal day electric."""
    from optimizer.thermal_house import house_year_result

    ambient = [-2.0 + 0.3 * hour for hour in range(24)]
    plan = tls.plan_live_house_horizon(
        _source(), house_profile=_PROFILE, ambient_forecast_c=ambient
    )
    index = pd.date_range(datetime.combine(_DAY, time(0)), periods=24, freq="h")
    year = house_year_result(
        living_area_m2=157.0,
        building_class=2,
        heat_pump_type="erde",
        persons=2,
        latitude=47.4,
        longitude=9.7,
        target_temp_c=21.5,
        heating_limit_c=15.0,
        hp_electric_kw=1.9,
        hourly_temperature_c=pd.Series(ambient, index=index),
        building_mass="leicht",
        house_tolerance_c=0.5,
        house_heat_loss_kw_per_k=_H,
    )

    assert round(sum(plan.electric_by_hour), 3) == year.daily_electric_kwh[0]
    assert plan.house_temp_c == pytest.approx(year.hourly_house_temp_c)
    assert plan.solar_source == tls.SOLAR_SOURCE_NONE


def test_house_horizon_cold_needs_more_than_mild(fixed_h):
    cold = tls.plan_live_house_horizon(
        _source(), house_profile=_PROFILE, ambient_forecast_c=[-8.0] * 24
    )
    mild = tls.plan_live_house_horizon(
        _source(), house_profile=_PROFILE, ambient_forecast_c=[14.0] * 24
    )

    assert sum(cold.electric_by_hour) > sum(mild.electric_by_hour) > 0.0


def test_legacy_without_living_area_nets_collector_per_day(monkeypatch):
    start = datetime.combine(_DAY, time(20))
    monkeypatch.setattr(
        tls,
        "resolve_live_collector_solar_kw",
        lambda *_a, **_k: ([0.0] * 4 + [2.0] * 4, tls.SOLAR_SOURCE_FORECAST),
    )
    plan = tls.plan_live_house_horizon(
        _source(living_area_m2=0.0, solar_thermal_area_m2=6.0),
        house_profile=_PROFILE,
        ambient_forecast_c=[0.0] * 8,
        start=start,
    )

    jaz = 4.3  # "erde"
    ww_kw = 2 * 2.0 / 24.0
    first_day = 4 * ww_kw / jaz / 4  # 20:00–23:00, no collector heat
    assert plan.electric_by_hour[:4] == pytest.approx([first_day] * 4)
    # Next day: 4 h warm water (~0.67 kWh_th) fully covered by 8 kWh_th collector heat.
    assert plan.electric_by_hour[4:] == [0.0] * 4
    assert plan.solar_source == tls.SOLAR_SOURCE_FORECAST
    assert plan.house_temp_c == []


def _live_matrix(hours: int) -> list[dict]:
    start = datetime.combine(_DAY, time(22))
    rows = []
    for index in range(hours * 4):
        slot = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "consumption_mode": "live_snapshot",
            }
        )
    return rows


def _plan(electric_by_hour: list[float]) -> tls.LiveHousePlan:
    return tls.LiveHousePlan(electric_by_hour, [21.5] * len(electric_by_hour), tls.SOLAR_SOURCE_NONE)


def test_live_context_without_storage_uses_house_plan(monkeypatch):
    import optimizer.thermal_flex_context as tfc
    from house_config.planning_flex_bridge import planning_thermal_to_milp

    def _no_year_profile(*_a, **_k):
        raise AssertionError("Live without storage must not build the year profile")

    monkeypatch.setattr(tfc, "_slot_aligned_thermal_energy_kwh", _no_year_profile)
    monkeypatch.setattr(tls, "live_house_plan_for_matrix", lambda *_a, **_k: _plan([0.4, 1.9, 0.0]))
    monkeypatch.setattr(
        "optimizer.absent_mode.resolve_absent_status", lambda _p: {"effective": False}
    )
    consumer = planning_thermal_to_milp(_source())
    profile = {**_PROFILE, "consumers": [_source()]}

    ctx = tfc.resolve_thermal_flex_contexts(_live_matrix(3), [consumer], profile)[consumer["id"]]

    assert ctx["slot_energy_kwh"] == [0.1] * 4 + [0.475] * 4 + [0.0] * 4
    # 22:00 + 23:00 belong to _DAY; the 00:00 hour (next day) plans 0 kWh.
    assert ctx["daily_targets"] == {_DAY: 2.3}
    assert ctx["targets_slot_aligned"] is True
    assert "live_store_start_c" not in ctx


def test_live_horizon_target_without_storage_uses_house_plan(monkeypatch):
    from optimizer.targets import resolve_thermal_annual_horizon_kwh

    def _no_calendar_days(*_a, **_k):
        raise AssertionError("Live without storage must not sum calendar-day HDD targets")

    monkeypatch.setattr(
        "optimizer.thermal_flex_context.thermal_daily_kwh_for_date", _no_calendar_days
    )
    monkeypatch.setattr(tls, "live_house_plan_for_matrix", lambda *_a, **_k: _plan([0.4, 1.9, 0.0]))
    monkeypatch.setattr(
        "config.get_resolved_runtime_settings",
        lambda: {"_house_profile": {**_PROFILE, "consumers": [_source()]}},
    )
    monkeypatch.setattr(
        "optimizer.absent_mode.resolve_absent_status", lambda _p: {"effective": False}
    )

    need = resolve_thermal_annual_horizon_kwh(
        {"id": "wp_heating", "daily_target_source": "thermal_annual"}, _live_matrix(3)
    )

    assert need == pytest.approx(2.3)


def test_one_house_plan_per_cycle(monkeypatch, fixed_h):
    builds = {"n": 0}
    original = tls.plan_live_house_horizon

    def _count(*args, **kwargs):
        builds["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(tls, "plan_live_house_horizon", _count)
    monkeypatch.setattr(tls, "_live_ambient_forecast", lambda horizon_h: [0.0] * horizon_h)
    matrix = _live_matrix(3)

    with live_cycle_scope():
        first = tls.live_house_plan_for_matrix(_source(), _PROFILE, matrix)
        second = tls.live_house_plan_for_matrix(_source(), _PROFILE, matrix)

    assert first is second
    assert builds["n"] == 1


def test_house_plan_none_with_storage():
    storage = {
        "volume_liters": 887.0,
        "heat_loss_kw_per_k": 0.01,
        "setpoint_c": 47.0,
        "tolerance_c": 5.0,
    }
    assert tls.live_house_plan_for_matrix(
        _source(heat_storage=storage), _PROFILE, _live_matrix(1)
    ) is None
