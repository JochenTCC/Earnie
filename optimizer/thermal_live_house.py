"""Live house plan without heat storage (split from thermal_live_store)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from optimizer.thermal_house import (
    DEFAULT_HOUSE_TOLERANCE_C,
    house_capacity_kwh_per_k,
)
from runtime_store.planning_clock import planning_now
from optimizer.thermal_live_solar import (
    SOLAR_SOURCE_NONE,
)
from optimizer.thermal_live_ref import live


def _thermal_with_nominal(thermal: dict, consumer: dict) -> dict:
    """Same parameter key as baseload (``consumer_annual_kwh``): WP kW on thermal."""
    if "nominal_power_kw" in thermal:
        return thermal
    return {**thermal, "nominal_power_kw": float(consumer.get("nominal_power_kw", 3.0) or 3.0)}


@dataclass(frozen=True)
class LiveHousePlan:
    """Live horizon plan of a ``thermal_annual`` consumer without heat storage (P4)."""

    electric_by_hour: list[float]
    # Simulated indoor temperature; empty on the legacy path without Wohnfläche.
    house_temp_c: list[float]
    # Collector credit source (legacy path only); SOLAR_SOURCE_NONE otherwise.
    solar_source: str


def plan_live_house_horizon(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    start: datetime | None = None,
) -> LiveHousePlan:
    """House RC + WP over the horizon, same hourly rules as the year sim without store.

    Start = target temperature (no indoor sensor; spec section 7 Q2). Envelope H
    from ``ThermalParameters``. Without Wohnfläche: legacy warm-water need minus
    a per-day collector credit (forecast irradiance, P3).
    """
    from data.heating_need import heat_pump_jaz, warm_water_kwh_week
    from optimizer.thermal_house import _step_hour_direct_wp

    if not ambient_forecast_c:
        raise ValueError("ambient_forecast_c darf nicht leer sein")
    thermal = consumer.get("thermal") or consumer
    jaz = heat_pump_jaz(str(thermal.get("heat_pump_type", "luft")))
    ww_kw = warm_water_kwh_week(int(thermal.get("persons", 2) or 2)) / 7.0 / 24.0
    living = float(thermal.get("living_area_m2", 0.0) or 0.0)
    if living <= 0.0:
        return _plan_live_legacy_ww(
            thermal, house_profile, ambient_forecast_c, ww_kw=ww_kw, jaz=jaz, start=start
        )
    from optimizer.thermal_parameters import house_thermal_parameters

    house_h = house_thermal_parameters(
        _thermal_with_nominal(thermal, consumer), house_profile=house_profile
    ).house_heat_loss_kw_per_k
    wp_kw = max(
        0.1,
        float(thermal.get("nominal_power_kw") or consumer.get("nominal_power_kw") or 3.0),
    )
    target = float(thermal.get("target_temp_c", 21.5) or 21.5)
    tol_raw = thermal.get("house_tolerance_c")
    tol = DEFAULT_HOUSE_TOLERANCE_C if tol_raw in (None, "") else max(0.05, float(tol_raw))
    house_c = house_capacity_kwh_per_k(living, thermal.get("building_mass"))
    house_temp = target
    electric_by_hour: list[float] = []
    house_temps: list[float] = []
    for ambient in ambient_forecast_c:
        house_temp, electric = _step_hour_direct_wp(
            house_temp=house_temp,
            ambient_c=float(ambient),
            house_c=house_c,
            house_h=float(house_h),
            house_band_min=target - tol,
            max_heat_kw=wp_kw * jaz,
            wp_kw=wp_kw,
            ww_electric_kw=ww_kw / jaz if jaz > 0 else 0.0,
        )
        electric_by_hour.append(float(electric))
        house_temps.append(float(house_temp))
    return LiveHousePlan(electric_by_hour, house_temps, SOLAR_SOURCE_NONE)


def _plan_live_legacy_ww(
    thermal: dict,
    house_profile: dict,
    ambient_forecast_c: list[float],
    *,
    ww_kw: float,
    jaz: float,
    start: datetime | None,
) -> LiveHousePlan:
    """Legacy open-loop path (no Wohnfläche): warm water minus collector, netted per day."""
    horizon = len(ambient_forecast_c)
    start_dt = (start or planning_now()).replace(minute=0, second=0, microsecond=0)
    solar, solar_source = live.resolve_live_collector_solar_kw(
        thermal, house_profile, horizon, start=start_dt
    )
    offsets_by_day: dict[Any, list[int]] = {}
    for offset in range(horizon):
        day = (start_dt + timedelta(hours=offset)).date()
        offsets_by_day.setdefault(day, []).append(offset)
    electric_by_hour = [0.0] * horizon
    for offsets in offsets_by_day.values():
        heat = ww_kw * len(offsets)
        credit = sum(solar[offset] for offset in offsets)
        net_electric = max(0.0, heat - credit) / jaz if jaz > 0 else 0.0
        for offset in offsets:
            electric_by_hour[offset] = net_electric / len(offsets)
    return LiveHousePlan(electric_by_hour, [], solar_source)
