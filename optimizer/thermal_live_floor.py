"""Open-loop store floor simulation helpers (split from thermal_live_store)."""
from __future__ import annotations
from dataclasses import dataclass
from optimizer.thermal_coupled import (
    step_coupled_hour,
)
from optimizer.thermal_house import (
    DEFAULT_HOUSE_TOLERANCE_C,
    house_capacity_kwh_per_k,
    house_requests_heat,
    step_house_hour,
)
from optimizer.thermal_model import ThermalBand


def _ww_kw(persons: int) -> float:
    from data.heating_need import warm_water_kwh_week

    return warm_water_kwh_week(int(persons)) / 7.0 / 24.0


@dataclass(frozen=True)
class _HouseLiveParams:
    use_house: bool
    house_c: float
    house_h: float
    house_band_min: float
    house_temp: float
    max_heat: float
    house_target_c: float
    heating_limit_c: float


def _resolve_house_live_params(
    *,
    living_area_m2: float,
    building_mass: str | None,
    target_temp_c: float,
    house_tolerance_c: float | None,
    house_heat_loss_kw_per_k: float | None,
    heating_limit_c: float,
    start_house_temp_c: float | None,
    max_heat: float,
) -> _HouseLiveParams:
    house_temp = float(
        start_house_temp_c if start_house_temp_c is not None else target_temp_c
    )
    target = float(target_temp_c)
    limit = float(heating_limit_c)
    use_house = float(living_area_m2) > 0.0
    if not use_house:
        return _HouseLiveParams(
            False, 0.0, 0.0, target, house_temp, max_heat, target, limit
        )
    if house_heat_loss_kw_per_k is None or float(house_heat_loss_kw_per_k) <= 0.0:
        # H comes from ThermalParameters (reference-year calibration); a short
        # Live forecast alone inflates H by ~8760/n (thermals-p2 §Live store floor).
        raise ValueError(
            "Live-Speicherplan mit Wohnfläche braucht house_heat_loss_kw_per_k "
            "(optimizer.thermal_parameters.house_thermal_parameters)."
        )
    tol = (
        DEFAULT_HOUSE_TOLERANCE_C
        if house_tolerance_c is None
        else max(0.05, float(house_tolerance_c))
    )
    return _HouseLiveParams(
        True,
        house_capacity_kwh_per_k(living_area_m2, building_mass),
        float(house_heat_loss_kw_per_k),
        target - tol,
        house_temp,
        max_heat,
        target,
        limit,
    )


# Recover toward target at most this many K per Euler hour. Full C·ΔT in one hour
# emptied a warm buffer (~5 K drop) and forced WP while T_eq was still above band_max.
_MAX_HOUSE_CLIMB_K_PER_H = 0.1


def _space_heat_demand_kw(
    house: _HouseLiveParams,
    house_temp: float,
    ambient: float,
) -> float:
    """Store draw for space heat: envelope hold / rate-limited climb — not WP dump.

    Using ``max_heat`` as continuous demand emptied a hot buffer (e.g. 67 °C) in
    ~3 h and forced Freigabe while T_eq was still far above setpoint. Pulling
    ``C·(target−T)`` in one hour (leicht Bauweise) caused the same early drain.
    """
    if not house.use_house:
        return 0.0
    if float(ambient) >= house.heating_limit_c - 1e-9:
        return 0.0
    if not house_requests_heat(
        house_temp,
        ambient,
        capacity_kwh_per_k=house.house_c,
        heat_loss_kw_per_k=house.house_h,
        band_min_c=house.house_band_min,
    ):
        return 0.0
    loss = house.house_h * (float(house_temp) - float(ambient))
    delta_k = max(0.0, house.house_target_c - float(house_temp))
    climb = min(delta_k, _MAX_HOUSE_CLIMB_K_PER_H) * house.house_c
    return min(house.max_heat, max(0.0, loss + climb))


def _simulate_store_floor_hours(
    *,
    start_temp_c: float,
    ambient_forecast_c: list[float],
    solar: list[float],
    band: ThermalBand,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    wp_kw: float,
    jaz_f: float,
    ww: float,
    house: _HouseLiveParams,
) -> tuple[list[bool], list[float], float, list[float]]:
    store_temp = float(start_temp_c)
    house_temp = house.house_temp
    forced: list[bool] = []
    electric_by_hour: list[float] = []
    store_temps: list[float] = []
    floor_electric = 0.0
    for hour, ambient_raw in enumerate(ambient_forecast_c):
        ambient = float(ambient_raw)
        space_kw = _space_heat_demand_kw(house, house_temp, ambient)
        result = step_coupled_hour(
            store_temp,
            ambient,
            solar_kw=float(solar[hour]),
            demand_kw=space_kw + ww,
            capacity_kwh_per_k=capacity_kwh_per_k,
            heat_loss_kw_per_k=heat_loss_kw_per_k,
            band=band,
            wp_electric_kw=wp_kw,
            jaz=jaz_f,
        )
        forced.append(bool(result.wp_on))
        electric_by_hour.append(float(result.electric_kwh))
        if result.wp_on:
            floor_electric += float(result.electric_kwh)
        store_temp = result.temp_c
        store_temps.append(float(store_temp))
        if house.use_house:
            house_temp = step_house_hour(
                house_temp,
                ambient,
                heat_in_kw=space_kw,
                capacity_kwh_per_k=house.house_c,
                heat_loss_kw_per_k=house.house_h,
            )
    return forced, electric_by_hour, floor_electric, store_temps


def _apply_t_low_near_term_force(
    forced: list[bool],
    electric_by_hour: list[float],
    floor_electric: float,
    *,
    temp_low_c: float | None,
    band: ThermalBand,
    wp_kw: float,
) -> tuple[list[bool], list[float], float, bool]:
    if temp_low_c is None or float(temp_low_c) >= band.min_c - 1e-9:
        return forced, electric_by_hour, floor_electric, False
    forced = list(forced)
    electric_by_hour = list(electric_by_hour)
    forced[0] = True
    if electric_by_hour[0] <= 1e-12:
        electric_by_hour[0] = wp_kw
        floor_electric += wp_kw
    return forced, electric_by_hour, floor_electric, True
