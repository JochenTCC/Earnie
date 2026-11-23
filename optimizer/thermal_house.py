"""Thermals P2 — house indoor single-node RC (DIN V 18599 Bauweise).

Import facade: the RC primitives live in ``thermal_house_rc``, the hour loop and climate rows
in ``thermal_house_sim``; this module keeps the memoized year simulation and its calibration.
"""
from __future__ import annotations

from optimizer.thermal_house_rc import (  # noqa: F401  (re-exported)
    BUILDING_MASS_C_WH_PER_M2K,
    CALIBRATION_ENERGY_TOL_KWH,
    CALIBRATION_MAX_ITER,
    CALIBRATION_REL_TOL,
    DEFAULT_BUILDING_MASS,
    DEFAULT_HOUSE_TOLERANCE_C,
    VENT_MARGIN_K,
    HouseYearResult,
    calibrate_house_heat_loss_kw_per_k,
    calibrate_house_heat_loss_with_gains,
    cool_house_temp,
    house_capacity_kwh_per_k,
    house_requests_heat,
    ideal_space_heat_kwh,
    normalize_building_mass,
    resolve_house_heat_loss_kw_per_k,
    step_house_hour,
    vent_house_temp,
)
from optimizer.thermal_house_sim import (  # noqa: F401  (re-exported)
    _climate_rows,
    _flat_ambient_from_daily,
    _flat_ambient_from_day_rows,
    _init_store_state,
    _own_electric_kwh,
    _simulate_rows,
    _solar_gain_rows,
    _split_input_energy,
    _step_hour_direct_wp,
    _step_hour_with_store,
)


def _house_year_cache_key(kwargs: dict) -> tuple:
    from optimizer.thermal_year_cache import call_key

    # Callers pass different subsets of the keyword arguments (e.g. the chart path
    # omits ``cooling`` / ``heating_booked``); key on the effective call so the
    # same simulation is shared between them.
    key = call_key({**_SIMULATE_HOUSE_YEAR_DEFAULTS, **kwargs})
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


def _keyword_defaults(func) -> dict:
    import inspect

    return {
        name: param.default
        for name, param in inspect.signature(func).parameters.items()
        if param.default is not inspect.Parameter.empty
    }


def house_year_result(**kwargs) -> HouseYearResult:
    """Year simulation with house RC; memoized on the full inputs (see ``_simulate_house_year``)."""
    from optimizer.thermal_year_cache import HOUSE_YEAR_CACHE

    return HOUSE_YEAR_CACHE.get_or_compute(
        _house_year_cache_key(kwargs),
        lambda: _simulate_house_year(**kwargs),
        _copy_house_year_result,
    )


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
    _check_house_year_inputs(call_kwargs)
    day_rows, sim_common, annual_heat = _house_year_setup(call_kwargs)
    return _calibrate_house_year(call_kwargs, day_rows, sim_common, annual_heat)


def _check_house_year_inputs(kw: dict) -> None:
    """Fail loud on a missing living area or window irradiance with solar gains switched on."""
    from house_config.house_gains import solar_gains_active

    if float(kw["living_area_m2"]) <= 0.0:
        raise ValueError("living_area_m2 muss > 0 sein für House-RC")
    solar_on = solar_gains_active({"solar_gains": kw["solar_gains"]})
    if solar_on and kw["hourly_solar_gain_kw"] is None:
        raise ValueError(
            "Solare Gewinne sind eingeschaltet (thermal.solar_gains.enabled), aber es fehlt die "
            "stündliche Fenster-Einstrahlung: die Jahressimulation braucht das Open-Meteo-Archiv "
            "(Offline-Klima mit Tageswerten kann keine Fenstergewinne rechnen)."
        )


def _house_year_setup(kw: dict) -> tuple[list, dict, float]:
    """(day rows, shared ``_simulate_rows`` kwargs, annual space heat target) of one call."""
    from data.heating_need import _resolve_climate_series

    area_m2 = float(kw["solar_thermal_area_m2"])
    daily_temps, daily_radiation_mj, _calendar = _resolve_climate_series(
        latitude=kw["latitude"],
        longitude=kw["longitude"],
        daily_temps=kw["daily_temps"],
        daily_radiation_mj=kw["daily_radiation_mj"],
        solar_thermal_area_m2=area_m2,
        hourly_temperature_c=kw["hourly_temperature_c"],
        hourly_collector_wm2=kw["hourly_collector_wm2"],
    )
    sim_common = _house_year_shared_params(
        living_area_m2=kw["living_area_m2"],
        gross_floor_area_m2=kw["gross_floor_area_m2"],
        building_class=kw["building_class"],
        heat_efficiency=kw["heat_efficiency"],
        persons=kw["persons"],
        hp_electric_kw=kw["hp_electric_kw"],
        target_temp_c=kw["target_temp_c"],
        hwb_kwh_m2=kw["hwb_kwh_m2"],
        building_mass=kw["building_mass"],
        house_tolerance_c=kw["house_tolerance_c"],
        heat_storage=kw["heat_storage"],
    )
    annual_heat = sim_common.pop("annual_heat")
    sim_common["start_house_temp_c"] = kw["start_house_temp_c"]
    sim_common["start_store_temp_c"] = kw["start_store_temp_c"]
    sim_common["cooling"] = kw["cooling"]

    day_rows = _climate_rows(
        latitude=kw["latitude"],
        hourly_temperature_c=kw["hourly_temperature_c"],
        hourly_collector_wm2=kw["hourly_collector_wm2"],
        daily_temps=daily_temps,
        daily_radiation_mj=daily_radiation_mj,
        area_m2=area_m2,
        solar_thermal_tilt_deg=float(kw["solar_thermal_tilt_deg"]),
        solar_thermal_azimuth_deg=float(kw["solar_thermal_azimuth_deg"]),
    )
    return day_rows, sim_common, annual_heat


def _house_year_gains(kw: dict, day_rows: list) -> tuple[list[float], bool, float, float | None]:
    """(fixed gain kW per hour, has Grundlast gain, other consumers kWh, reference electric)."""
    from optimizer.house_gains import consumer_gain_kw, other_consumers_annual_kwh

    internal_gains = kw["internal_gains"]
    hours = 24 * len(day_rows)
    fixed_gain = [
        solar + internal
        for solar, internal in zip(
            _solar_gain_rows(kw["hourly_solar_gain_kw"], day_rows),
            consumer_gain_kw(internal_gains, hours=hours),
        )
    ]
    has_baseload_gain = bool(internal_gains) and float(
        internal_gains.get("baseload_factor", 0.0) or 0.0
    ) > 0.0
    others_kwh = other_consumers_annual_kwh(internal_gains) if has_baseload_gain else 0.0
    reference_electric = (
        _reference_heating_electric_kwh(kw)
        if has_baseload_gain and internal_gains.get("reference_heating")
        else None
    )
    return fixed_gain, has_baseload_gain, others_kwh, reference_electric


def _calibrate_house_year(
    kw: dict, day_rows: list, sim_common: dict, annual_heat: float
) -> HouseYearResult:
    """Fixed point of envelope H and the Grundlast gain (depends on the house's own draw)."""
    from optimizer.house_gains import baseload_gain_kw

    fixed_gain, has_baseload_gain, others_kwh, reference_electric = _house_year_gains(
        kw, day_rows
    )
    internal_gains = kw["internal_gains"]
    target_temp_c = kw["target_temp_c"]
    heat_electric, heating_booked = kw["heat_electric"], kw["heating_booked"]
    fixed_h = _override_h(kw["house_heat_loss_kw_per_k"])
    start_h = calibrate_house_heat_loss_kw_per_k(
        annual_heat,
        _flat_ambient_from_day_rows(day_rows),
        target_temp_c=target_temp_c,
        heating_limit_c=kw["heating_limit_c"],
    )
    ambient = _flat_ambient_from_day_rows(day_rows)
    # Scenario variant: the Grundlast is fixed by the installed system, no fixed point.
    electric = 0.0 if reference_electric is None else reference_electric
    diff = 0.0
    for iteration in range(CALIBRATION_MAX_ITER):
        base_kw = baseload_gain_kw(
            internal_gains, others_kwh=others_kwh, own_electric_kwh=electric
        )
        gains = [g + base_kw for g in fixed_gain] if base_kw > 0.0 else fixed_gain
        house_h = fixed_h
        if house_h is None:
            house_h = calibrate_house_heat_loss_with_gains(
                annual_heat,
                ambient,
                gains,
                capacity_kwh_per_k=sim_common["house_c"],
                target_temp_c=target_temp_c,
                start_h=start_h,
            )
        result = _simulate_rows(
            day_rows=day_rows, house_h=house_h, gain_by_hour=gains, **sim_common
        )
        new_electric = _own_electric_kwh(
            result, heat_electric=heat_electric, heating_booked=heating_booked
        )
        diff = abs(new_electric - electric)
        fixed_point = not has_baseload_gain or reference_electric is not None
        if fixed_point or _grundlast_converged(diff, new_electric):
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


def _override_h(override: float | None) -> float | None:
    """The configured envelope H when set and > 0, else None (calibrate)."""
    return float(override) if override is not None and float(override) > 0.0 else None


def _grundlast_converged(diff: float, new_electric: float) -> bool:
    """The Grundlast ↔ heating-electric fixed point holds within the calibration tolerance."""
    return diff <= max(CALIBRATION_ENERGY_TOL_KWH, CALIBRATION_REL_TOL * new_electric)


def _reference_heating_electric_kwh(call_kwargs: dict) -> float:
    """Annual electric draw of the installed heating (scenario variant, Grundlast basis)."""
    gains = dict(call_kwargs["internal_gains"])
    reference = gains.pop("reference_heating")
    kwargs = {**call_kwargs, **reference}
    kwargs["internal_gains"] = gains
    result = house_year_result(**kwargs)
    return float(sum(result.daily_electric_kwh)) + float(sum(result.hourly_cooling_electric_kw))


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


_SIMULATE_HOUSE_YEAR_DEFAULTS = _keyword_defaults(_simulate_house_year)
