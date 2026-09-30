"""Thermals P2 — house indoor single-node RC (DIN V 18599 Bauweise)."""
from __future__ import annotations

from dataclasses import dataclass

BUILDING_MASS_C_WH_PER_M2K: dict[str, float] = {
    "leicht": 50.0,
    "mittel": 90.0,
    "schwer": 130.0,
}

DEFAULT_BUILDING_MASS = "mittel"
DEFAULT_HOUSE_TOLERANCE_C = 0.5


def normalize_building_mass(raw: object | None) -> str:
    """Return leicht|mittel|schwer; unknown → mittel."""
    key = str(raw or DEFAULT_BUILDING_MASS).strip().lower()
    if key not in BUILDING_MASS_C_WH_PER_M2K:
        return DEFAULT_BUILDING_MASS
    return key


def house_capacity_kwh_per_k(living_area_m2: float, building_mass: str | None) -> float:
    """Effective house heat capacity C [kWh/K] from Wohnfläche × Bauweise."""
    area = max(0.0, float(living_area_m2))
    mass = normalize_building_mass(building_mass)
    return area * BUILDING_MASS_C_WH_PER_M2K[mass] / 1000.0


def calibrate_house_heat_loss_kw_per_k(
    annual_heat_kwh: float,
    ambient_c: list[float],
    *,
    target_temp_c: float,
    heating_limit_c: float,
) -> float:
    """Envelope H [kW/K] so annual heat ≈ HWB·area under HDD-like ambient."""
    denom = 0.0
    target = float(target_temp_c)
    limit = float(heating_limit_c)
    for ambient in ambient_c:
        t_out = float(ambient)
        if t_out < limit:
            denom += max(0.0, target - t_out)
    if denom <= 1e-9:
        return 0.0
    return max(0.0, float(annual_heat_kwh) / denom)


def resolve_house_heat_loss_kw_per_k(
    *,
    override_kw_per_k: float | None,
    annual_heat_kwh: float,
    ambient_c: list[float],
    target_temp_c: float,
    heating_limit_c: float,
) -> float:
    if override_kw_per_k is not None and float(override_kw_per_k) > 0.0:
        return float(override_kw_per_k)
    return calibrate_house_heat_loss_kw_per_k(
        annual_heat_kwh,
        ambient_c,
        target_temp_c=target_temp_c,
        heating_limit_c=heating_limit_c,
    )


def step_house_hour(
    temp_c: float,
    ambient_c: float,
    *,
    heat_in_kw: float,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
) -> float:
    """One Euler hour for indoor air / shallow mass."""
    if capacity_kwh_per_k <= 0:
        raise ValueError("capacity_kwh_per_k muss > 0 sein")
    loss = float(heat_loss_kw_per_k) * (float(temp_c) - float(ambient_c))
    net = float(heat_in_kw) - loss
    return float(temp_c) + net / capacity_kwh_per_k


def house_requests_heat(
    temp_c: float,
    ambient_c: float,
    *,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    band_min_c: float,
) -> bool:
    """True when projected next temp without heat would fall below band min."""
    next_off = step_house_hour(
        temp_c,
        ambient_c,
        heat_in_kw=0.0,
        capacity_kwh_per_k=capacity_kwh_per_k,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
    )
    return next_off < band_min_c - 1e-9


@dataclass(frozen=True)
class HouseYearResult:
    """Daily WP electric plus hourly house (and optional store) temperatures."""

    daily_electric_kwh: list[float]
    hourly_house_temp_c: list[float]
    hourly_store_temp_c: list[float]


def _flat_ambient_from_daily(daily_temps: list[float]) -> list[float]:
    out: list[float] = []
    for temp in daily_temps:
        out.extend([float(temp)] * 24)
    return out


def _flat_ambient_from_day_rows(
    day_rows: list,
) -> list[float]:
    out: list[float] = []
    for _day, amb, _solar in day_rows:
        out.extend(float(t) for t in amb)
    return out


def _step_hour_with_store(
    *,
    store_temp: float,
    house_temp: float,
    ambient_c: float,
    solar_kw: float,
    ww_kw: float,
    house_c: float,
    house_h: float,
    house_band_min: float,
    max_heat_kw: float,
    store_capacity: float,
    store_u: float,
    store_band,
    wp_kw: float,
    jaz: float,
) -> tuple[float, float, float]:
    """One hour with store: returns (store_temp, house_temp, electric_kwh)."""
    from optimizer.thermal_coupled import step_coupled_hour

    request = house_requests_heat(
        house_temp,
        ambient_c,
        capacity_kwh_per_k=house_c,
        heat_loss_kw_per_k=house_h,
        band_min_c=house_band_min,
    )
    space_kw = max_heat_kw if request else 0.0
    result = step_coupled_hour(
        store_temp,
        ambient_c,
        solar_kw=solar_kw,
        demand_kw=space_kw + ww_kw,
        capacity_kwh_per_k=store_capacity,
        heat_loss_kw_per_k=store_u,
        band=store_band,
        wp_electric_kw=wp_kw,
        jaz=jaz,
    )
    next_house = step_house_hour(
        house_temp,
        ambient_c,
        heat_in_kw=space_kw,
        capacity_kwh_per_k=house_c,
        heat_loss_kw_per_k=house_h,
    )
    return result.temp_c, next_house, result.electric_kwh


def _step_hour_direct_wp(
    *,
    house_temp: float,
    ambient_c: float,
    house_c: float,
    house_h: float,
    house_band_min: float,
    max_heat_kw: float,
    wp_kw: float,
    ww_electric_kw: float,
) -> tuple[float, float]:
    """One hour without store: returns (house_temp, electric_kwh)."""
    request = house_requests_heat(
        house_temp,
        ambient_c,
        capacity_kwh_per_k=house_c,
        heat_loss_kw_per_k=house_h,
        band_min_c=house_band_min,
    )
    heat_in = max_heat_kw if request else 0.0
    electric = (wp_kw if request else 0.0) + ww_electric_kw
    next_house = step_house_hour(
        house_temp,
        ambient_c,
        heat_in_kw=heat_in,
        capacity_kwh_per_k=house_c,
        heat_loss_kw_per_k=house_h,
    )
    return next_house, electric


def house_year_result(
    *,
    living_area_m2: float,
    building_class: int,
    heat_pump_type: str,
    persons: int,
    latitude: float,
    longitude: float,
    target_temp_c: float,
    heating_limit_c: float,
    hp_electric_kw: float,
    heat_storage: dict | None = None,
    daily_temps: list[float] | None = None,
    daily_radiation_mj: list[float] | None = None,
    hourly_temperature_c=None,
    hourly_collector_wm2=None,
    hwb_kwh_m2: float | None = None,
    solar_thermal_area_m2: float = 0.0,
    solar_thermal_tilt_deg: float = 18.0,
    solar_thermal_azimuth_deg: float = 0.0,
    building_mass: str | None = None,
    house_tolerance_c: float | None = None,
    house_heat_loss_kw_per_k: float | None = None,
    start_house_temp_c: float | None = None,
    start_store_temp_c: float | None = None,
) -> HouseYearResult:
    """Year simulation with house RC; optional heat storage coupling."""
    from data.heating_need import (
        _resolve_climate_series,
        daily_solar_thermal_kwh,
        heat_pump_jaz,
        specific_heating_kwh_m2,
        warm_water_kwh_week,
    )
    from optimizer.thermal_coupled import (
        _group_hourly_by_day,
        _hourly_solar_from_daily,
        heat_storage_enabled,
        normalize_heat_storage,
    )
    from optimizer.thermal_model import (
        ThermalBand,
        capacity_kwh_per_k_from_volume,
    )

    if float(living_area_m2) <= 0.0:
        raise ValueError("living_area_m2 muss > 0 sein für House-RC")

    area_m2 = float(solar_thermal_area_m2)
    daily_temps, daily_radiation_mj, _calendar = _resolve_climate_series(
        latitude=latitude,
        longitude=longitude,
        daily_temps=daily_temps,
        daily_radiation_mj=daily_radiation_mj,
        solar_thermal_area_m2=area_m2,
        hourly_temperature_c=hourly_temperature_c,
        hourly_collector_wm2=hourly_collector_wm2,
    )
    annual_heat = float(living_area_m2) * specific_heating_kwh_m2(
        building_class, hwb_kwh_m2=hwb_kwh_m2
    )
    ww_day = warm_water_kwh_week(persons) / 7.0
    jaz = heat_pump_jaz(heat_pump_type)
    wp_kw = max(0.1, float(hp_electric_kw))
    max_heat = wp_kw * jaz
    house_c = house_capacity_kwh_per_k(living_area_m2, building_mass)
    tol = (
        DEFAULT_HOUSE_TOLERANCE_C
        if house_tolerance_c is None
        else max(0.05, float(house_tolerance_c))
    )
    band_min = float(target_temp_c) - tol
    storage = (
        normalize_heat_storage(heat_storage)
        if heat_storage_enabled(heat_storage)
        else None
    )

    if hourly_temperature_c is not None:
        day_rows = _group_hourly_by_day(
            hourly_temperature_c, hourly_collector_wm2, area_m2
        )
        ambient_flat = _flat_ambient_from_day_rows(day_rows)
        house_h = resolve_house_heat_loss_kw_per_k(
            override_kw_per_k=house_heat_loss_kw_per_k,
            annual_heat_kwh=annual_heat,
            ambient_c=ambient_flat,
            target_temp_c=target_temp_c,
            heating_limit_c=heating_limit_c,
        )
        return _simulate_house_hourly_rows(
            day_rows=day_rows,
            ww_day=ww_day,
            house_c=house_c,
            house_h=house_h,
            band_min=band_min,
            max_heat=max_heat,
            wp_kw=wp_kw,
            jaz=jaz,
            target_temp_c=target_temp_c,
            storage=storage,
            start_house_temp_c=start_house_temp_c,
            start_store_temp_c=start_store_temp_c,
        )

    ambient_flat = _flat_ambient_from_daily(daily_temps)
    house_h = resolve_house_heat_loss_kw_per_k(
        override_kw_per_k=house_heat_loss_kw_per_k,
        annual_heat_kwh=annual_heat,
        ambient_c=ambient_flat,
        target_temp_c=target_temp_c,
        heating_limit_c=heating_limit_c,
    )
    return _simulate_house_daily_climate(
        daily_temps=daily_temps,
        daily_radiation_mj=daily_radiation_mj,
        area_m2=area_m2,
        latitude=latitude,
        solar_thermal_tilt_deg=float(solar_thermal_tilt_deg),
        solar_thermal_azimuth_deg=float(solar_thermal_azimuth_deg),
        ww_day=ww_day,
        house_c=house_c,
        house_h=house_h,
        band_min=band_min,
        max_heat=max_heat,
        wp_kw=wp_kw,
        jaz=jaz,
        target_temp_c=target_temp_c,
        storage=storage,
        start_house_temp_c=start_house_temp_c,
        start_store_temp_c=start_store_temp_c,
        daily_solar_thermal_kwh=daily_solar_thermal_kwh,
        hourly_solar_from_daily=_hourly_solar_from_daily,
    )


def _simulate_house_hourly_rows(
    *,
    day_rows: list,
    ww_day: float,
    house_c: float,
    house_h: float,
    band_min: float,
    max_heat: float,
    wp_kw: float,
    jaz: float,
    target_temp_c: float,
    storage: dict | None,
    start_house_temp_c: float | None,
    start_store_temp_c: float | None,
) -> HouseYearResult:
    from optimizer.thermal_model import (
        ThermalBand,
        capacity_kwh_per_k_from_volume,
    )

    ww_kw = ww_day / 24.0
    house_temp = float(
        start_house_temp_c if start_house_temp_c is not None else target_temp_c
    )
    daily_out: list[float] = []
    house_temps: list[float] = []
    store_temps: list[float] = []
    store_temp = 0.0
    store_capacity = 0.0
    store_u = 0.0
    store_band = None
    if storage is not None:
        store_capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
        store_u = float(storage["heat_loss_kw_per_k"])
        store_band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
        store_temp = float(
            start_store_temp_c
            if start_store_temp_c is not None
            else store_band.setpoint_c
        )

    for _day, amb, solar_hours in day_rows:
        day_electric = 0.0
        for hour in range(24):
            ambient = amb[hour]
            if storage is not None and store_band is not None:
                store_temp, house_temp, electric = _step_hour_with_store(
                    store_temp=store_temp,
                    house_temp=house_temp,
                    ambient_c=ambient,
                    solar_kw=solar_hours[hour],
                    ww_kw=ww_kw,
                    house_c=house_c,
                    house_h=house_h,
                    house_band_min=band_min,
                    max_heat_kw=max_heat,
                    store_capacity=store_capacity,
                    store_u=store_u,
                    store_band=store_band,
                    wp_kw=wp_kw,
                    jaz=jaz,
                )
                store_temps.append(store_temp)
            else:
                house_temp, electric = _step_hour_direct_wp(
                    house_temp=house_temp,
                    ambient_c=ambient,
                    house_c=house_c,
                    house_h=house_h,
                    house_band_min=band_min,
                    max_heat_kw=max_heat,
                    wp_kw=wp_kw,
                    ww_electric_kw=ww_kw / jaz if jaz > 0 else 0.0,
                )
            day_electric += electric
            house_temps.append(house_temp)
        daily_out.append(round(day_electric, 3))
    return HouseYearResult(daily_out, house_temps, store_temps)


def _simulate_house_daily_climate(
    *,
    daily_temps: list[float],
    daily_radiation_mj: list[float] | None,
    area_m2: float,
    latitude: float,
    solar_thermal_tilt_deg: float,
    solar_thermal_azimuth_deg: float,
    ww_day: float,
    house_c: float,
    house_h: float,
    band_min: float,
    max_heat: float,
    wp_kw: float,
    jaz: float,
    target_temp_c: float,
    storage: dict | None,
    start_house_temp_c: float | None,
    start_store_temp_c: float | None,
    daily_solar_thermal_kwh,
    hourly_solar_from_daily,
) -> HouseYearResult:
    from optimizer.thermal_model import (
        ThermalBand,
        capacity_kwh_per_k_from_volume,
    )

    ww_kw = ww_day / 24.0
    house_temp = float(
        start_house_temp_c if start_house_temp_c is not None else target_temp_c
    )
    daily_out: list[float] = []
    house_temps: list[float] = []
    store_temps: list[float] = []
    store_temp = 0.0
    store_capacity = 0.0
    store_u = 0.0
    store_band = None
    if storage is not None:
        store_capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
        store_u = float(storage["heat_loss_kw_per_k"])
        store_band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
        store_temp = float(
            start_store_temp_c
            if start_store_temp_c is not None
            else store_band.setpoint_c
        )

    for day_idx, ambient_day in enumerate(daily_temps):
        solar_day = 0.0
        if area_m2 > 0.0 and daily_radiation_mj:
            solar_day = daily_solar_thermal_kwh(
                daily_radiation_mj,
                day_idx,
                area_m2,
                latitude,
                solar_thermal_tilt_deg,
                solar_thermal_azimuth_deg,
            )
        solar_hours = hourly_solar_from_daily(solar_day)
        day_electric = 0.0
        for hour in range(24):
            if storage is not None and store_band is not None:
                store_temp, house_temp, electric = _step_hour_with_store(
                    store_temp=store_temp,
                    house_temp=house_temp,
                    ambient_c=float(ambient_day),
                    solar_kw=solar_hours[hour],
                    ww_kw=ww_kw,
                    house_c=house_c,
                    house_h=house_h,
                    house_band_min=band_min,
                    max_heat_kw=max_heat,
                    store_capacity=store_capacity,
                    store_u=store_u,
                    store_band=store_band,
                    wp_kw=wp_kw,
                    jaz=jaz,
                )
                store_temps.append(store_temp)
            else:
                house_temp, electric = _step_hour_direct_wp(
                    house_temp=house_temp,
                    ambient_c=float(ambient_day),
                    house_c=house_c,
                    house_h=house_h,
                    house_band_min=band_min,
                    max_heat_kw=max_heat,
                    wp_kw=wp_kw,
                    ww_electric_kw=ww_kw / jaz if jaz > 0 else 0.0,
                )
            day_electric += electric
            house_temps.append(house_temp)
        daily_out.append(round(day_electric, 3))
    return HouseYearResult(daily_out, house_temps, store_temps)
