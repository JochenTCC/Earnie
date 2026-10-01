"""Live open-loop heat-storage floor + opportunistic headroom (Thermals P2 / 2.7.b).

No MILP store-T SoC: physics stay outside the solver; callers get forced hours and
scalar kWh bounds only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optimizer.thermal_coupled import (
    heat_storage_enabled,
    normalize_heat_storage,
    step_coupled_hour,
)
from optimizer.thermal_house import (
    DEFAULT_HOUSE_TOLERANCE_C,
    house_capacity_kwh_per_k,
    house_requests_heat,
    resolve_house_heat_loss_kw_per_k,
    step_house_hour,
)
from optimizer.thermal_model import ThermalBand, capacity_kwh_per_k_from_volume, heat_content_kwh


@dataclass(frozen=True)
class HeatStorageReadings:
    temp_eq_c: float
    temp_low_c: float | None
    used_measured_eq: bool
    used_measured_low: bool


@dataclass(frozen=True)
class LiveStorePlan:
    forced_hour_flags: list[bool]
    floor_electric_kwh: float
    opp_cap_electric_kwh: float
    start_temp_c: float
    temp_low_c: float | None
    used_measured_eq: bool
    used_measured_low: bool
    band: ThermalBand
    electric_by_hour: list[float]
    store_temp_c: list[float] = field(default_factory=list)
    q_sim_kwh: list[float] = field(default_factory=list)


def resolve_heat_storage_setpoint_band(heat_storage: dict) -> ThermalBand:
    storage = normalize_heat_storage(heat_storage)
    if storage is None:
        raise ValueError("heat_storage ist nicht aktiv (volume_liters <= 0)")
    return ThermalBand(storage["setpoint_c"], storage["tolerance_c"])


def resolve_heat_storage_readings(
    consumer: dict,
    *,
    house_doc: dict | None = None,
    heat_storage: dict | None = None,
) -> HeatStorageReadings:
    """Read T_eq / T_low; missing T_eq falls back to store setpoint."""
    from integrations.loxone_client import fetch_heat_storage_temps

    storage = normalize_heat_storage(
        heat_storage
        if heat_storage is not None
        else (consumer.get("thermal") or {}).get("heat_storage")
        or consumer.get("heat_storage")
    )
    if storage is None:
        raise ValueError("heat_storage ist nicht aktiv")
    band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
    measured = fetch_heat_storage_temps(consumer, house_doc=house_doc)
    eq = measured.get("temp_eq_c")
    low = measured.get("temp_low_c")
    used_eq = eq is not None
    return HeatStorageReadings(
        temp_eq_c=float(eq) if used_eq else float(band.setpoint_c),
        temp_low_c=float(low) if low is not None else None,
        used_measured_eq=used_eq,
        used_measured_low=low is not None,
    )


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


def _year_ambient_for_house_h(house_profile: dict | None) -> list[float] | None:
    """Full-year outdoor series for envelope H calibration (not the Live forecast)."""
    if not isinstance(house_profile, dict):
        return None
    try:
        from datetime import datetime

        from data.modeled_climate import ModeledClimateContext

        climate = ModeledClimateContext.for_house_profile(house_profile, kwp=0.0)
        bundle = climate._bundle_for_calendar_year(datetime.now().year)
        temps = bundle.temperature_c
        if temps is None or len(temps) < 24 * 30:
            return None
        return [float(t) for t in temps.tolist()]
    except Exception:
        return None


def _resolve_live_house_heat_loss_kw_per_k(
    *,
    override_kw_per_k: float | None,
    annual_heat_kwh: float,
    ambient_forecast_c: list[float],
    target_temp_c: float,
    heating_limit_c: float,
    house_profile: dict | None = None,
) -> float:
    """Calibrate H from year climate when possible; never from a short Live forecast alone."""
    if override_kw_per_k is not None and float(override_kw_per_k) > 0.0:
        return float(override_kw_per_k)
    year_ambient = _year_ambient_for_house_h(house_profile)
    if year_ambient:
        return resolve_house_heat_loss_kw_per_k(
            override_kw_per_k=None,
            annual_heat_kwh=float(annual_heat_kwh),
            ambient_c=year_ambient,
            target_temp_c=float(target_temp_c),
            heating_limit_c=float(heating_limit_c),
        )
    # Fallback: scale short-forecast calibration up to year length (order-of-magnitude).
    n = max(1, len(ambient_forecast_c))
    raw = resolve_house_heat_loss_kw_per_k(
        override_kw_per_k=None,
        annual_heat_kwh=float(annual_heat_kwh),
        ambient_c=[float(t) for t in ambient_forecast_c],
        target_temp_c=float(target_temp_c),
        heating_limit_c=float(heating_limit_c),
    )
    return float(raw) * (n / 8760.0)


def _resolve_house_live_params(
    *,
    living_area_m2: float,
    building_mass: str | None,
    target_temp_c: float,
    house_tolerance_c: float | None,
    house_heat_loss_kw_per_k: float | None,
    heating_limit_c: float,
    annual_heat_kwh: float,
    ambient_forecast_c: list[float],
    start_house_temp_c: float | None,
    max_heat: float,
    house_profile: dict | None = None,
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
    tol = (
        DEFAULT_HOUSE_TOLERANCE_C
        if house_tolerance_c is None
        else max(0.05, float(house_tolerance_c))
    )
    return _HouseLiveParams(
        True,
        house_capacity_kwh_per_k(living_area_m2, building_mass),
        _resolve_live_house_heat_loss_kw_per_k(
            override_kw_per_k=house_heat_loss_kw_per_k,
            annual_heat_kwh=float(annual_heat_kwh),
            ambient_forecast_c=ambient_forecast_c,
            target_temp_c=target,
            heating_limit_c=limit,
            house_profile=house_profile,
        ),
        target - tol,
        house_temp,
        max_heat,
        target,
        limit,
    )


def _space_heat_demand_kw(
    house: _HouseLiveParams,
    house_temp: float,
    ambient: float,
) -> float:
    """Store draw for space heat: envelope hold / climb — not full WP dump.

    Using ``max_heat`` as continuous demand emptied a hot buffer (e.g. 67 °C) in
    ~3 h and forced Freigabe while T_eq was still far above setpoint.
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
    climb = (house.house_target_c - float(house_temp)) * house.house_c
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


def plan_live_store_horizon(
    *,
    start_temp_c: float,
    ambient_forecast_c: list[float],
    band: ThermalBand,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    wp_electric_kw: float,
    jaz: float,
    temp_low_c: float | None = None,
    solar_forecast_kw: list[float] | None = None,
    living_area_m2: float = 0.0,
    building_mass: str | None = None,
    target_temp_c: float = 21.5,
    house_tolerance_c: float | None = None,
    house_heat_loss_kw_per_k: float | None = None,
    heating_limit_c: float = 15.0,
    annual_heat_kwh: float = 0.0,
    persons: int = 2,
    start_house_temp_c: float | None = None,
    used_measured_eq: bool = False,
    used_measured_low: bool = False,
    house_profile: dict | None = None,
) -> LiveStorePlan:
    """Bang-bang floor on T_eq plus optional T_low near-term force; opp headroom."""
    horizon = len(ambient_forecast_c)
    if horizon < 1:
        raise ValueError("ambient_forecast_c darf nicht leer sein")
    wp_kw = max(0.1, float(wp_electric_kw))
    jaz_f = max(1e-9, float(jaz))
    solar = list(solar_forecast_kw or [0.0] * horizon)
    if len(solar) < horizon:
        solar = solar + [0.0] * (horizon - len(solar))
    house = _resolve_house_live_params(
        living_area_m2=living_area_m2,
        building_mass=building_mass,
        target_temp_c=target_temp_c,
        house_tolerance_c=house_tolerance_c,
        house_heat_loss_kw_per_k=house_heat_loss_kw_per_k,
        heating_limit_c=heating_limit_c,
        annual_heat_kwh=annual_heat_kwh,
        ambient_forecast_c=ambient_forecast_c,
        start_house_temp_c=start_house_temp_c,
        max_heat=wp_kw * jaz_f,
        house_profile=house_profile,
    )
    forced, electric_by_hour, floor_electric, store_temps = _simulate_store_floor_hours(
        start_temp_c=start_temp_c,
        ambient_forecast_c=ambient_forecast_c,
        solar=solar,
        band=band,
        capacity_kwh_per_k=capacity_kwh_per_k,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        wp_kw=wp_kw,
        jaz_f=jaz_f,
        ww=_ww_kw(persons),
        house=house,
    )
    forced, electric_by_hour, floor_electric, low_forced = _apply_t_low_near_term_force(
        forced,
        electric_by_hour,
        floor_electric,
        temp_low_c=temp_low_c,
        band=band,
        wp_kw=wp_kw,
    )
    fill_thermal = max(
        0.0, (band.setpoint_c - float(start_temp_c)) * capacity_kwh_per_k
    )
    opp_cap = max(0.0, fill_thermal / jaz_f - floor_electric)
    q_sim = [
        heat_content_kwh(temp_c, capacity_kwh_per_k) for temp_c in store_temps
    ]
    return LiveStorePlan(
        forced_hour_flags=forced,
        floor_electric_kwh=round(floor_electric, 3),
        opp_cap_electric_kwh=round(opp_cap, 3),
        start_temp_c=round(float(start_temp_c), 3),
        temp_low_c=None if temp_low_c is None else round(float(temp_low_c), 3),
        used_measured_eq=bool(used_measured_eq),
        used_measured_low=bool(used_measured_low) or low_forced,
        band=band,
        electric_by_hour=electric_by_hour,
        store_temp_c=store_temps,
        q_sim_kwh=q_sim,
    )


def plan_live_store_for_thermal_consumer(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    solar_forecast_kw: list[float] | None = None,
    house_doc: dict | None = None,
) -> LiveStorePlan | None:
    """Build Live store plan from a thermal_annual house consumer; None if no store."""
    from data.heating_need import heat_pump_jaz, specific_heating_kwh_m2

    thermal = consumer.get("thermal") or consumer
    storage_raw = thermal.get("heat_storage")
    if not heat_storage_enabled(storage_raw):
        return None
    storage = normalize_heat_storage(storage_raw)
    if storage is None:
        return None
    band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
    readings = resolve_heat_storage_readings(
        consumer, house_doc=house_doc, heat_storage=storage
    )
    capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    wp_kw = float(
        thermal.get("nominal_power_kw")
        or consumer.get("nominal_power_kw")
        or 3.0
    )
    living = float(thermal.get("living_area_m2", 0.0) or 0.0)
    hwb = thermal.get("hwb_kwh_m2")
    annual = living * specific_heating_kwh_m2(
        int(thermal.get("building_class", 3) or 3),
        hwb_kwh_m2=float(hwb) if hwb not in (None, "") else None,
    )
    return plan_live_store_horizon(
        start_temp_c=readings.temp_eq_c,
        ambient_forecast_c=ambient_forecast_c,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=float(storage["heat_loss_kw_per_k"]),
        wp_electric_kw=wp_kw,
        jaz=heat_pump_jaz(str(thermal.get("heat_pump_type", "luft"))),
        temp_low_c=readings.temp_low_c,
        solar_forecast_kw=solar_forecast_kw,
        living_area_m2=living,
        building_mass=thermal.get("building_mass"),
        target_temp_c=float(thermal.get("target_temp_c", 21.5) or 21.5),
        house_tolerance_c=thermal.get("house_tolerance_c"),
        house_heat_loss_kw_per_k=thermal.get("house_heat_loss_kw_per_k"),
        heating_limit_c=float(thermal.get("heating_limit_c", 15.0) or 15.0),
        annual_heat_kwh=annual,
        persons=int(thermal.get("persons", 2) or 2),
        used_measured_eq=readings.used_measured_eq,
        used_measured_low=readings.used_measured_low,
        house_profile=house_profile,
    )


def map_forced_hours_to_slot_indices(
    matrix: list,
    forced_hour_flags: list[bool],
    *,
    eligible_indices: list[int] | None = None,
) -> list[int]:
    """Map hour flags onto matrix QH indices (wall-clock hour match from horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime

    if not matrix or not forced_hour_flags:
        return []
    eligible = set(eligible_indices) if eligible_indices is not None else None
    start = matrix_slot_datetime(matrix, 0)
    forced_slots: list[int] = []
    for index, _row in enumerate(matrix):
        if eligible is not None and index not in eligible:
            continue
        slot_dt = matrix_slot_datetime(matrix, index)
        hour_offset = int((slot_dt - start).total_seconds() // 3600)
        if hour_offset < 0 or hour_offset >= len(forced_hour_flags):
            continue
        if forced_hour_flags[hour_offset]:
            forced_slots.append(index)
    return forced_slots


def live_min_kwh_by_day(matrix: list, plan: LiveStorePlan) -> dict[Any, float]:
    """Flexible Live day lower bound: opportunistic headroom to setpoint on first day.

    Bang-bang floor energy is enforced only via ``forced_indices`` (correct timing).
    Putting floor kWh into a movable day budget made MILP heat while the store was
    still hot (e.g. 60 °C) to satisfy later floor hours — including hours outside
    the MILP window.
    """
    from optimizer.charging_context import matrix_slot_datetime

    if not matrix:
        return {}
    if plan.opp_cap_electric_kwh <= 1e-9:
        return {}
    first_day = matrix_slot_datetime(matrix, 0).date()
    return {first_day: round(float(plan.opp_cap_electric_kwh), 3)}


def build_heat_storage_observability(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    house_doc: dict | None = None,
    solar_forecast_kw: list[float] | None = None,
) -> dict[str, Any] | None:
    """Snapshot for optimization_history: T_eq/T_low + Q_meas/Q_sim."""
    plan = plan_live_store_for_thermal_consumer(
        consumer,
        house_profile=house_profile,
        ambient_forecast_c=ambient_forecast_c,
        solar_forecast_kw=solar_forecast_kw,
        house_doc=house_doc,
    )
    if plan is None:
        return None
    thermal = consumer.get("thermal") or consumer
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    if storage is None:
        return None
    capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    q_meas = heat_content_kwh(plan.start_temp_c, capacity)
    q_sim = (
        float(plan.q_sim_kwh[0])
        if plan.q_sim_kwh
        else heat_content_kwh(plan.start_temp_c, capacity)
    )
    return {
        "consumer_id": consumer.get("id"),
        "kind": "heat_storage",
        "readings_c": {
            "temp_eq": plan.start_temp_c,
            "temp_low": plan.temp_low_c,
            "setpoint": plan.band.setpoint_c,
            "tolerance": plan.band.tolerance_c,
            "band_min": plan.band.min_c,
            "band_max": plan.band.max_c,
        },
        "heat_content_kwh": {
            "q_meas": round(q_meas, 3),
            "q_sim": round(q_sim, 3),
        },
        "model": {
            "capacity_kwh_per_k": round(capacity, 4),
            "volume_liters": float(storage["volume_liters"]),
            "heat_loss_kw_per_k": float(storage["heat_loss_kw_per_k"]),
        },
        "used_measured_eq": plan.used_measured_eq,
        "used_measured_low": plan.used_measured_low,
        "horizon_q_sim_kwh": [round(v, 3) for v in plan.q_sim_kwh],
    }


def collect_heat_storage_observability(
    consumers: list[dict],
    *,
    house_profile: dict,
    horizon: int = 24,
    house_doc: dict | None = None,
) -> list[dict[str, Any]]:
    """Observability for thermal_annual consumers with active heat_storage."""
    from data.outdoor_forecast import get_outdoor_forecast_with_fallback

    results: list[dict[str, Any]] = []
    fallback_ambient = 10.0
    try:
        from integrations.loxone_client import _read_optional_temp_c
        from settings.ehal_marker_resolve import marker_sens_temperature_outside

        live_amb = _read_optional_temp_c(marker_sens_temperature_outside(house_doc=house_doc))
        if live_amb is not None:
            fallback_ambient = float(live_amb)
    except Exception:
        pass
    ambient_forecast, _src = get_outdoor_forecast_with_fallback(
        horizon=max(1, int(horizon)),
        fallback_ambient_c=fallback_ambient,
    )
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        if consumer.get("type") != "thermal_annual":
            continue
        thermal = consumer.get("thermal") or consumer
        if not heat_storage_enabled(thermal.get("heat_storage")):
            continue
        cid = consumer.get("id") or "?"
        try:
            item = build_heat_storage_observability(
                consumer,
                house_profile=house_profile,
                ambient_forecast_c=ambient_forecast,
                house_doc=house_doc,
            )
            if item is not None:
                results.append(item)
        except Exception as exc:
            results.append(
                {
                    "consumer_id": cid,
                    "kind": "heat_storage",
                    "error": str(exc),
                }
            )
    return results
