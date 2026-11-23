"""House RC year hour loop and climate rows (split from thermal_house)."""
from __future__ import annotations

from optimizer.thermal_house_rc import (
    HouseYearResult,
    cool_house_temp,
    house_requests_heat,
    step_house_hour,
    vent_house_temp,
)


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
    gain_kw: float = 0.0,
    target_temp_c: float | None = None,
) -> tuple[float, float, float, float]:
    """One hour with store: returns (store_temp, house_temp, electric_kwh, space_heat_kwh)."""
    from optimizer.thermal_coupled import step_coupled_hour

    request = house_requests_heat(
        house_temp,
        ambient_c,
        capacity_kwh_per_k=house_c,
        heat_loss_kw_per_k=house_h,
        band_min_c=house_band_min,
        gain_kw=gain_kw,
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
        gain_kw=gain_kw,
    )
    if target_temp_c is not None:
        next_house = vent_house_temp(next_house, ambient_c, target_temp_c)
    return result.temp_c, next_house, result.electric_kwh, space_kw


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
    gain_kw: float = 0.0,
    target_temp_c: float | None = None,
) -> tuple[float, float]:
    """One hour without store: returns (house_temp, electric_kwh)."""
    request = house_requests_heat(
        house_temp,
        ambient_c,
        capacity_kwh_per_k=house_c,
        heat_loss_kw_per_k=house_h,
        band_min_c=house_band_min,
        gain_kw=gain_kw,
    )
    heat_in = max_heat_kw if request else 0.0
    electric = (wp_kw if request else 0.0) + ww_electric_kw
    next_house = step_house_hour(
        house_temp,
        ambient_c,
        heat_in_kw=heat_in,
        capacity_kwh_per_k=house_c,
        heat_loss_kw_per_k=house_h,
        gain_kw=gain_kw,
    )
    if target_temp_c is not None:
        next_house = vent_house_temp(next_house, ambient_c, target_temp_c)
    return next_house, electric


def _climate_rows(
    *,
    latitude: float,
    hourly_temperature_c,
    hourly_collector_wm2,
    daily_temps: list[float],
    daily_radiation_mj: list[float] | None,
    area_m2: float,
    solar_thermal_tilt_deg: float,
    solar_thermal_azimuth_deg: float,
) -> list[tuple[object, list[float], list[float]]]:
    """(day, ambient[24], collector kW[24]) rows for either climate source."""
    from data.heating_need import daily_solar_thermal_kwh
    from optimizer.thermal_coupled import _group_hourly_by_day, _hourly_solar_from_daily

    if hourly_temperature_c is not None:
        return _group_hourly_by_day(hourly_temperature_c, hourly_collector_wm2, area_m2)
    rows = []
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
        rows.append((day_idx, [float(ambient_day)] * 24, _hourly_solar_from_daily(solar_day)))
    return rows


def _solar_gain_rows(hourly_solar_gain_kw, day_rows: list) -> list[float]:
    """Window gain kW per simulated hour, aligned with ``day_rows`` by date and hour."""
    hours = 24 * len(day_rows)
    if hourly_solar_gain_kw is None:
        return [0.0] * hours
    import pandas as pd

    by_day: dict = {}
    for ts, value in hourly_solar_gain_kw.items():
        stamp = pd.Timestamp(ts)
        slot = by_day.setdefault(stamp.date(), [0.0] * 24)
        slot[int(stamp.hour)] += 0.0 if pd.isna(value) else float(value)
    out: list[float] = []
    for day, _amb, _solar in day_rows:
        out.extend(by_day.get(day, [0.0] * 24))
    return out


def _own_electric_kwh(
    result: HouseYearResult, *, heat_electric: bool, heating_booked: bool
) -> float:
    """Electricity of the house's heating and cooling (not part of the Grundlast)."""
    heating = float(sum(result.daily_electric_kwh)) if heat_electric and heating_booked else 0.0
    return heating + float(sum(result.hourly_cooling_electric_kw))


def _split_input_energy(
    result: HouseYearResult, *, heat_electric: bool, heating_booked: bool = True
) -> HouseYearResult:
    """The simulation books input energy (heat / efficiency); a fuel source draws no power.

    Heating not booked: both input series are 0 (the heating stays in the Grundlast).
    """
    zeros = [0.0] * len(result.daily_electric_kwh)
    if not heating_booked:
        electric, fuel = zeros, list(zeros)
    elif heat_electric:
        electric, fuel = result.daily_electric_kwh, zeros
    else:
        electric, fuel = zeros, list(result.daily_electric_kwh)
    return HouseYearResult(
        daily_electric_kwh=electric,
        hourly_house_temp_c=result.hourly_house_temp_c,
        hourly_store_temp_c=result.hourly_store_temp_c,
        daily_fuel_kwh=fuel,
        house_heat_loss_kw_per_k=result.house_heat_loss_kw_per_k,
        annual_space_heat_kwh=result.annual_space_heat_kwh,
        hourly_cooling_electric_kw=result.hourly_cooling_electric_kw,
        annual_cooling_kwh=result.annual_cooling_kwh,
    )


def _init_store_state(
    storage: dict | None, start_store_temp_c: float | None
) -> tuple[float, float, float, object | None]:
    """Initial (temp, capacity kWh/K, loss kW/K, band) of the heat store; zeros/None without store."""
    from optimizer.thermal_model import (
        ThermalBand,
        capacity_kwh_per_k_from_volume,
    )

    if storage is None:
        return 0.0, 0.0, 0.0, None
    store_capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    store_u = float(storage["heat_loss_kw_per_k"])
    store_band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
    store_temp = float(
        start_store_temp_c if start_store_temp_c is not None else store_band.setpoint_c
    )
    return store_temp, store_capacity, store_u, store_band


def _heat_hour(
    p: dict,
    store_temp: float,
    house_temp: float,
    ambient: float,
    solar_hours,
    hour: int,
    gain: float,
) -> tuple[float, float, float, float]:
    """One heating hour: (store_temp, house_temp, electric_kwh, space_heat_kwh)."""
    if p["storage"] is not None and p["store_band"] is not None:
        return _step_hour_with_store(
            store_temp=store_temp,
            house_temp=house_temp,
            ambient_c=ambient,
            solar_kw=solar_hours[hour],
            ww_kw=p["ww_kw"],
            house_c=p["house_c"],
            house_h=p["house_h"],
            house_band_min=p["band_min"],
            max_heat_kw=p["max_heat"],
            store_capacity=p["store_capacity"],
            store_u=p["store_u"],
            store_band=p["store_band"],
            wp_kw=p["wp_kw"],
            jaz=p["jaz"],
            gain_kw=gain,
            target_temp_c=p["target_temp_c"],
        )
    house_temp, electric = _step_hour_direct_wp(
        house_temp=house_temp,
        ambient_c=ambient,
        house_c=p["house_c"],
        house_h=p["house_h"],
        house_band_min=p["band_min"],
        max_heat_kw=p["max_heat"],
        wp_kw=p["wp_kw"],
        ww_electric_kw=p["ww_electric_kw"],
        gain_kw=gain,
        target_temp_c=p["target_temp_c"],
    )
    # The heat pump ran this hour iff it drew more than the warm-water share.
    space = p["max_heat"] if electric > p["ww_electric_kw"] + 1e-12 else 0.0
    return store_temp, house_temp, electric, space


def _simulate_rows(
    *,
    day_rows: list,
    gain_by_hour: list[float],
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
    cooling: dict | None = None,
) -> HouseYearResult:
    """Hour loop over (day, ambient[24], collector kW[24]) rows with gains per hour.

    With ``cooling`` the air conditioning takes the house back to its setpoint after each hour.
    """
    ww_kw = ww_day / 24.0
    house_temp = float(
        start_house_temp_c if start_house_temp_c is not None else target_temp_c
    )
    daily_out: list[float] = []
    house_temps: list[float] = []
    store_temps: list[float] = []
    space_heat = 0.0
    store_temp, store_capacity, store_u, store_band = _init_store_state(
        storage, start_store_temp_c
    )
    params = {
        "storage": storage,
        "store_band": store_band,
        "store_capacity": store_capacity,
        "store_u": store_u,
        "ww_kw": ww_kw,
        "ww_electric_kw": ww_kw / jaz if jaz > 0 else 0.0,
        "house_c": house_c,
        "house_h": house_h,
        "band_min": band_min,
        "max_heat": max_heat,
        "wp_kw": wp_kw,
        "jaz": jaz,
        "target_temp_c": target_temp_c,
    }
    with_store = storage is not None and store_band is not None
    cooling_electric: list[float] = []
    cold_total = 0.0
    hour_index = 0
    for _day, amb, solar_hours in day_rows:
        day_electric = 0.0
        for hour in range(24):
            store_temp, house_temp, electric, space = _heat_hour(
                params,
                store_temp,
                house_temp,
                float(amb[hour]),
                solar_hours,
                hour,
                gain_by_hour[hour_index],
            )
            hour_index += 1
            if with_store:
                store_temps.append(store_temp)
            space_heat += space
            day_electric += electric
            if cooling is not None:
                house_temp, cold = cool_house_temp(
                    house_temp,
                    setpoint_c=cooling["setpoint_c"],
                    cooling_power_kw=cooling["cooling_power_kw"],
                    capacity_kwh_per_k=house_c,
                )
                cold_total += cold
                cooling_electric.append(cold / float(cooling["seer"]))
            house_temps.append(house_temp)
        daily_out.append(round(day_electric, 3))
    return HouseYearResult(
        daily_out,
        house_temps,
        store_temps,
        house_heat_loss_kw_per_k=float(house_h),
        annual_space_heat_kwh=round(space_heat, 3),
        hourly_cooling_electric_kw=cooling_electric,
        annual_cooling_kwh=round(cold_total, 3),
    )
