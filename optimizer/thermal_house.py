"""Thermals P2 — house indoor single-node RC (DIN V 18599 Bauweise)."""
from __future__ import annotations

from dataclasses import dataclass, field

from house_config.profile_schema_defaults import house_thermal_default

BUILDING_MASS_C_WH_PER_M2K: dict[str, float] = {
    "leicht": 50.0,
    "mittel": 90.0,
    "schwer": 130.0,
}

DEFAULT_BUILDING_MASS = str(house_thermal_default("building_mass"))
DEFAULT_HOUSE_TOLERANCE_C = float(house_thermal_default("house_tolerance_c"))

# SUSI P2 [assumption]: gains above target + this margin are vented (windows, shading); the
# house never cools below the outdoor air that way. Without it a sunny house would overheat
# without bound and carry the heat into the next heating period.
VENT_MARGIN_K = 3.0
# H calibration with gains (SUSI P2): the ideal-heater space heat (no power limit, so H stays a
# building property) matches HWB × BGF within this share; the Grundlast ↔ heating-electric
# fixed point within CALIBRATION_ENERGY_TOL_KWH.
CALIBRATION_REL_TOL = 0.005
CALIBRATION_ENERGY_TOL_KWH = 1.0
CALIBRATION_MAX_ITER = 25


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
    gain_kw: float = 0.0,
) -> float:
    """One Euler hour for indoor air / shallow mass (heating plus solar / internal gains)."""
    if capacity_kwh_per_k <= 0:
        raise ValueError("capacity_kwh_per_k muss > 0 sein")
    loss = float(heat_loss_kw_per_k) * (float(temp_c) - float(ambient_c))
    net = float(heat_in_kw) + float(gain_kw) - loss
    return float(temp_c) + net / capacity_kwh_per_k


def vent_house_temp(temp_c: float, ambient_c: float, target_temp_c: float) -> float:
    """Cap the indoor temperature at target + ``VENT_MARGIN_K`` (not below the outdoor air)."""
    cap = max(float(target_temp_c) + VENT_MARGIN_K, float(ambient_c))
    return min(float(temp_c), cap)


def cool_house_temp(
    temp_c: float,
    *,
    setpoint_c: float,
    cooling_power_kw: float,
    capacity_kwh_per_k: float,
) -> tuple[float, float]:
    """Air conditioning for one hour: (indoor temp, cold kWh) after cooling down to the setpoint.

    The device removes the heat above ``setpoint_c`` up to its capacity (ideal thermostat; an
    undersized device leaves the house warmer).
    """
    excess = (float(temp_c) - float(setpoint_c)) * float(capacity_kwh_per_k)
    if excess <= 0.0:
        return float(temp_c), 0.0
    cold = min(excess, float(cooling_power_kw))
    return float(temp_c) - cold / float(capacity_kwh_per_k), cold


def house_requests_heat(
    temp_c: float,
    ambient_c: float,
    *,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    band_min_c: float,
    gain_kw: float = 0.0,
) -> bool:
    """True when projected next temp without heating (gains included) would fall below band min."""
    next_off = step_house_hour(
        temp_c,
        ambient_c,
        heat_in_kw=0.0,
        capacity_kwh_per_k=capacity_kwh_per_k,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        gain_kw=gain_kw,
    )
    return next_off < band_min_c - 1e-9


@dataclass(frozen=True)
class HouseYearResult:
    """Daily heat-source input energy plus hourly house (and optional store) temperatures.

    Input energy = delivered heat / efficiency; it is electric for a heat pump or
    ``electric_direct`` and fuel (final energy, kWh) for every other heat source.
    ``house_heat_loss_kw_per_k`` is the envelope H the run used (calibrated with gains, or the
    override); ``annual_space_heat_kwh`` the space heat delivered into the house (no warm water).
    With air conditioning, ``hourly_cooling_electric_kw`` is its electricity per hour (never in
    ``daily_electric_kwh``, which stays the heat source's input) and ``annual_cooling_kwh`` the
    cold it removed. Heating not booked (switch „Heizung betrachten“ off, cooling-only run):
    the heat source still holds the house temperature, but its input energy is 0.
    """

    daily_electric_kwh: list[float]
    hourly_house_temp_c: list[float]
    hourly_store_temp_c: list[float]
    daily_fuel_kwh: list[float] = field(default_factory=list)
    house_heat_loss_kw_per_k: float | None = None
    annual_space_heat_kwh: float = 0.0
    hourly_cooling_electric_kw: list[float] = field(default_factory=list)
    annual_cooling_kwh: float = 0.0


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


def _house_year_cache_key(kwargs: dict) -> tuple:
    from optimizer.thermal_year_cache import call_key

    key = call_key(kwargs)
    uses_fixture = kwargs.get("hourly_temperature_c") is None and (
        kwargs.get("daily_temps") is None or kwargs.get("daily_radiation_mj") is None
    )
    if not uses_fixture:
        return key
    # Offline climate fixture is read inside the simulation: key on its file state.
    from data.heating_need import _resolve_climate_fixture_path

    path = _resolve_climate_fixture_path()
    stamp = (str(path), path.stat().st_mtime_ns) if path is not None else None
    return key + (("_climate_fixture", stamp),)


def _copy_house_year_result(result: HouseYearResult) -> HouseYearResult:
    return HouseYearResult(
        daily_electric_kwh=list(result.daily_electric_kwh),
        hourly_house_temp_c=list(result.hourly_house_temp_c),
        hourly_store_temp_c=list(result.hourly_store_temp_c),
        daily_fuel_kwh=list(result.daily_fuel_kwh),
        house_heat_loss_kw_per_k=result.house_heat_loss_kw_per_k,
        annual_space_heat_kwh=result.annual_space_heat_kwh,
        hourly_cooling_electric_kw=list(result.hourly_cooling_electric_kw),
        annual_cooling_kwh=result.annual_cooling_kwh,
    )


def house_year_result(**kwargs) -> HouseYearResult:
    """Year simulation with house RC; memoized on the full inputs (see ``_simulate_house_year``)."""
    from optimizer.thermal_year_cache import HOUSE_YEAR_CACHE

    return HOUSE_YEAR_CACHE.get_or_compute(
        _house_year_cache_key(kwargs),
        lambda: _simulate_house_year(**kwargs),
        _copy_house_year_result,
    )


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


def _simulate_house_year(
    *,
    living_area_m2: float,
    building_class: int,
    heat_efficiency: float,
    heat_electric: bool = True,
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
    gross_floor_area_m2: float | None = None,
    internal_gains: dict | None = None,
    solar_gains: dict | None = None,
    hourly_solar_gain_kw=None,
    cooling: dict | None = None,
    heating_booked: bool = True,
) -> HouseYearResult:
    """Year simulation with house RC, gains, optional heat storage and air conditioning.

    Without an H override, H is calibrated so the simulated annual space heat (after solar and
    internal gains) equals HWB × BGF; the Grundlast part of the internal gains is solved in the
    same loop (it depends on the house's own electric draw: heating and cooling).
    ``cooling`` is the normalized ``cooling`` block (``house_config.house_cooling``); the
    calibration ignores it (ideal heater, building property). ``heating_booked=False`` books no
    heating input energy (cooling-only run of a house with „Heizung betrachten“ off).
    """
    call_kwargs = dict(locals())  # the call's keyword arguments (before any other local)
    from data.heating_need import _resolve_climate_series
    from house_config.house_gains import solar_gains_active
    from optimizer.house_gains import (
        baseload_gain_kw,
        consumer_gain_kw,
        other_consumers_annual_kwh,
    )

    if float(living_area_m2) <= 0.0:
        raise ValueError("living_area_m2 muss > 0 sein für House-RC")
    if solar_gains_active({"solar_gains": solar_gains}) and hourly_solar_gain_kw is None:
        raise ValueError(
            "Solare Gewinne sind eingeschaltet (thermal.solar_gains.enabled), aber es fehlt die "
            "stündliche Fenster-Einstrahlung: die Jahressimulation braucht das Open-Meteo-Archiv "
            "(Offline-Klima mit Tageswerten kann keine Fenstergewinne rechnen)."
        )

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
    sim_common = _house_year_shared_params(
        living_area_m2=living_area_m2,
        gross_floor_area_m2=gross_floor_area_m2,
        building_class=building_class,
        heat_efficiency=heat_efficiency,
        persons=persons,
        hp_electric_kw=hp_electric_kw,
        target_temp_c=target_temp_c,
        hwb_kwh_m2=hwb_kwh_m2,
        building_mass=building_mass,
        house_tolerance_c=house_tolerance_c,
        heat_storage=heat_storage,
    )
    annual_heat = sim_common.pop("annual_heat")
    sim_common["start_house_temp_c"] = start_house_temp_c
    sim_common["start_store_temp_c"] = start_store_temp_c
    sim_common["cooling"] = cooling

    day_rows = _climate_rows(
        latitude=latitude,
        hourly_temperature_c=hourly_temperature_c,
        hourly_collector_wm2=hourly_collector_wm2,
        daily_temps=daily_temps,
        daily_radiation_mj=daily_radiation_mj,
        area_m2=area_m2,
        solar_thermal_tilt_deg=float(solar_thermal_tilt_deg),
        solar_thermal_azimuth_deg=float(solar_thermal_azimuth_deg),
    )
    hours = 24 * len(day_rows)
    fixed_gain = [
        solar + internal
        for solar, internal in zip(
            _solar_gain_rows(hourly_solar_gain_kw, day_rows),
            consumer_gain_kw(internal_gains, hours=hours),
        )
    ]
    has_baseload_gain = bool(internal_gains) and float(
        internal_gains.get("baseload_factor", 0.0) or 0.0
    ) > 0.0
    others_kwh = other_consumers_annual_kwh(internal_gains) if has_baseload_gain else 0.0
    reference_electric = (
        _reference_heating_electric_kwh(call_kwargs)
        if has_baseload_gain and internal_gains.get("reference_heating")
        else None
    )

    override = house_heat_loss_kw_per_k
    fixed_h = float(override) if override is not None and float(override) > 0.0 else None
    start_h = calibrate_house_heat_loss_kw_per_k(
        annual_heat,
        _flat_ambient_from_day_rows(day_rows),
        target_temp_c=target_temp_c,
        heating_limit_c=heating_limit_c,
    )
    ambient = _flat_ambient_from_day_rows(day_rows)
    # Scenario variant: the Grundlast is fixed by the installed system, no fixed point.
    electric = 0.0 if reference_electric is None else reference_electric
    new_electric = 0.0
    diff = 0.0
    for iteration in range(CALIBRATION_MAX_ITER):
        base_kw = baseload_gain_kw(
            internal_gains, others_kwh=others_kwh, own_electric_kwh=electric
        )
        gains = [g + base_kw for g in fixed_gain] if base_kw > 0.0 else fixed_gain
        house_h = (
            fixed_h
            if fixed_h is not None
            else calibrate_house_heat_loss_with_gains(
                annual_heat,
                ambient,
                gains,
                capacity_kwh_per_k=sim_common["house_c"],
                target_temp_c=target_temp_c,
                start_h=start_h,
            )
        )
        result = _simulate_rows(
            day_rows=day_rows, house_h=house_h, gain_by_hour=gains, **sim_common
        )
        new_electric = _own_electric_kwh(
            result, heat_electric=heat_electric, heating_booked=heating_booked
        )
        diff = abs(new_electric - electric)
        if (
            not has_baseload_gain
            or reference_electric is not None
            or diff <= max(CALIBRATION_ENERGY_TOL_KWH, CALIBRATION_REL_TOL * new_electric)
        ):
            return _split_input_energy(
                result, heat_electric=heat_electric, heating_booked=heating_booked
            )
        # Damped update: the bang-bang heat pump makes the draw jump in steps, an undamped
        # update can cycle between two values.
        electric = new_electric if iteration < 2 else 0.5 * (electric + new_electric)
        start_h = house_h
    raise RuntimeError(
        "Hausmodell: Grundlast und Heizungsstrom konvergieren nicht "
        f"(letzte Differenz {diff:.1f} kWh)."
    )


def _reference_heating_electric_kwh(call_kwargs: dict) -> float:
    """Annual electric draw of the installed heating (scenario variant, Grundlast basis)."""
    gains = dict(call_kwargs["internal_gains"])
    reference = gains.pop("reference_heating")
    kwargs = {**call_kwargs, **reference}
    kwargs["internal_gains"] = gains
    result = house_year_result(**kwargs)
    return float(sum(result.daily_electric_kwh)) + float(sum(result.hourly_cooling_electric_kw))


def _own_electric_kwh(
    result: HouseYearResult, *, heat_electric: bool, heating_booked: bool
) -> float:
    """Electricity of the house's heating and cooling (not part of the Grundlast)."""
    heating = float(sum(result.daily_electric_kwh)) if heat_electric and heating_booked else 0.0
    return heating + float(sum(result.hourly_cooling_electric_kw))


def ideal_space_heat_kwh(
    house_h: float,
    ambient_c: list[float],
    gain_kw: list[float],
    *,
    capacity_kwh_per_k: float,
    target_temp_c: float,
) -> float:
    """Annual space heat of an ideal heater holding ``target_temp_c`` (no power limit).

    Gains above the need warm the mass (vented above target + ``VENT_MARGIN_K``) and are used
    in later hours; this is the building-only demand H is calibrated on.
    """
    temp = float(target_temp_c)
    target = float(target_temp_c)
    heat = 0.0
    c = float(capacity_kwh_per_k)
    for amb, gain in zip(ambient_c, gain_kw):
        free = temp + (gain - house_h * (temp - amb)) / c
        if free < target:
            heat += (target - free) * c
            temp = target
        else:
            temp = vent_house_temp(free, amb, target)
    return heat


def calibrate_house_heat_loss_with_gains(
    annual_heat_kwh: float,
    ambient_c: list[float],
    gain_kw: list[float],
    *,
    capacity_kwh_per_k: float,
    target_temp_c: float,
    start_h: float,
) -> float:
    """H [kW/K] whose ideal-heater space heat (after gains) equals ``annual_heat_kwh``.

    The heat grows monotonically with H: bracket from ``start_h`` (HDD estimate), then
    bisection with a secant step. Fails loud when no H reaches the target.
    """
    target = float(annual_heat_kwh)
    if target <= 0.0:
        return 0.0

    def heat_at(h: float) -> float:
        return ideal_space_heat_kwh(
            h,
            ambient_c,
            gain_kw,
            capacity_kwh_per_k=capacity_kwh_per_k,
            target_temp_c=target_temp_c,
        )

    lo_h, hi_h = 0.0, max(float(start_h), 1e-3)
    lo_q, hi_q = heat_at(lo_h), heat_at(hi_h)
    expansions = 0
    while hi_q < target:
        lo_h, lo_q = hi_h, hi_q
        hi_h *= 2.0
        hi_q = heat_at(hi_h)
        expansions += 1
        if expansions > 40:
            raise RuntimeError(
                f"Hausmodell: kein Verlustkoeffizient H erreicht {target:.0f} kWh Heizwärme "
                "(Klima zu warm für den HWB?)."
            )
    for _ in range(60):
        if abs(hi_q - target) <= CALIBRATION_REL_TOL * target * 0.2:
            return hi_h
        if abs(lo_q - target) <= CALIBRATION_REL_TOL * target * 0.2 and lo_h > 0.0:
            return lo_h
        span = hi_q - lo_q
        guess = lo_h + (target - lo_q) * (hi_h - lo_h) / span if span > 1e-9 else 0.0
        mid = 0.5 * (lo_h + hi_h)
        # Secant inside the inner 80 % of the bracket, else bisection.
        width = hi_h - lo_h
        h = guess if lo_h + 0.1 * width < guess < hi_h - 0.1 * width else mid
        q = heat_at(h)
        if q < target:
            lo_h, lo_q = h, q
        else:
            hi_h, hi_q = h, q
    return 0.5 * (lo_h + hi_h)


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


def annual_space_heat_target_kwh(
    *,
    living_area_m2: float,
    building_class: int,
    hwb_kwh_m2: float | None,
    gross_floor_area_m2: float | None = None,
) -> float:
    """HWB × Bruttogrundfläche (BGF explicit, else Wohnfläche × 1.25; SUSI P2)."""
    from data.heating_need import specific_heating_kwh_m2
    from house_config.house_gains import hwb_reference_area_m2

    area = hwb_reference_area_m2(
        {"living_area_m2": living_area_m2, "gross_floor_area_m2": gross_floor_area_m2}
    )
    return area * specific_heating_kwh_m2(building_class, hwb_kwh_m2=hwb_kwh_m2)


def _house_year_shared_params(
    *,
    living_area_m2: float,
    gross_floor_area_m2: float | None,
    building_class: int,
    heat_efficiency: float,
    persons: int,
    hp_electric_kw: float,
    target_temp_c: float,
    hwb_kwh_m2: float | None,
    building_mass: str | None,
    house_tolerance_c: float | None,
    heat_storage: dict | None,
) -> dict:
    """Heat-demand, heat-pump and house-RC inputs shared by both climate sources."""
    from data.heating_need import warm_water_kwh_week
    from optimizer.thermal_coupled import (
        heat_storage_enabled,
        normalize_heat_storage,
    )

    annual_heat = annual_space_heat_target_kwh(
        living_area_m2=living_area_m2,
        building_class=building_class,
        hwb_kwh_m2=hwb_kwh_m2,
        gross_floor_area_m2=gross_floor_area_m2,
    )
    ww_day = warm_water_kwh_week(persons) / 7.0
    if float(heat_efficiency) <= 0.0:
        raise ValueError(f"heat_efficiency muss > 0 sein (ist {heat_efficiency}).")
    jaz = float(heat_efficiency)
    wp_kw = max(0.1, float(hp_electric_kw))
    tol = (
        DEFAULT_HOUSE_TOLERANCE_C
        if house_tolerance_c is None
        else max(0.05, float(house_tolerance_c))
    )
    storage = (
        normalize_heat_storage(heat_storage)
        if heat_storage_enabled(heat_storage)
        else None
    )
    return {
        "annual_heat": annual_heat,
        "ww_day": ww_day,
        "jaz": jaz,
        "wp_kw": wp_kw,
        "max_heat": wp_kw * jaz,
        "house_c": house_capacity_kwh_per_k(living_area_m2, building_mass),
        "band_min": float(target_temp_c) - tol,
        "storage": storage,
        "target_temp_c": target_temp_c,
    }


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
    ww_electric_kw = ww_kw / jaz if jaz > 0 else 0.0
    cooling_electric: list[float] = []
    cold_total = 0.0
    hour_index = 0
    for _day, amb, solar_hours in day_rows:
        day_electric = 0.0
        for hour in range(24):
            ambient = float(amb[hour])
            gain = gain_by_hour[hour_index]
            hour_index += 1
            if storage is not None and store_band is not None:
                store_temp, house_temp, electric, space = _step_hour_with_store(
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
                    gain_kw=gain,
                    target_temp_c=target_temp_c,
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
                    ww_electric_kw=ww_electric_kw,
                    gain_kw=gain,
                    target_temp_c=target_temp_c,
                )
                # The heat pump ran this hour iff it drew more than the warm-water share.
                space = max_heat if electric > ww_electric_kw + 1e-12 else 0.0
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
