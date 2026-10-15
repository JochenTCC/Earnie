"""ThermalHorizon P1 — thermal parameters from one reference-year simulation.

The 8760 h year model runs only here, once per (thermal config, reference
climate year). Live planning simulates the horizon and reads these
parameters; it never needs a year series of its own.

Reference year = ``last_full_archive_year()``. Archive years are complete
and immutable, so the memo key does not include the climate cache file.
"""
from __future__ import annotations

from dataclasses import dataclass

SOURCE_YEAR_SIM = "year_sim"
SOURCE_OVERRIDE = "override"


@dataclass(frozen=True)
class ThermalParameters:
    reference_year: int
    annual_electric_kwh: float
    # Envelope H [kW/K]; None without Wohnfläche (legacy open-loop HDD path).
    house_heat_loss_kw_per_k: float | None
    # Where H comes from: calibrated on the reference year, or a config override.
    house_heat_loss_source: str | None


def thermal_with_geo(thermal: dict, house_profile: dict | None) -> dict:
    """``thermal`` with latitude/longitude, taken from the house profile when absent."""
    profile = house_profile or {}
    out = dict(thermal)
    for key in ("latitude", "longitude"):
        if out.get(key) is None:
            if profile.get(key) is None:
                raise ValueError(
                    f"Thermal-Parameter: {key} fehlt in thermal und Hausprofil."
                )
            out[key] = float(profile[key])
    return out


def house_thermal_parameters(
    thermal: dict,
    *,
    house_profile: dict | None = None,
    reference_year: int | None = None,
) -> ThermalParameters:
    """Annual WP electric kWh and envelope H for a ``thermal_annual`` consumer."""
    from data.modeled_climate import (
        _planning_timezone_for_thermal,
        collector_surface_from_thermal,
    )
    from data.open_meteo_solar_archive import last_full_archive_year
    from optimizer.thermal_year_cache import THERMAL_PARAMETERS_CACHE, fingerprint_json

    geo = thermal_with_geo(thermal, house_profile)
    year = reference_year if reference_year is not None else last_full_archive_year()
    profile = house_profile or {}
    # The house profile only enters via timezone and collector surface; keying on
    # those (not the whole profile) lets baseload and Live share one derivation.
    surface = collector_surface_from_thermal(
        geo, {**profile, "latitude": geo["latitude"], "longitude": geo["longitude"]}
    )
    key = (
        "house",
        fingerprint_json(geo),
        _planning_timezone_for_thermal(geo, profile),
        (surface.tilt_deg, surface.azimuth_deg),
        year,
    )
    return THERMAL_PARAMETERS_CACHE.get_or_compute(
        key,
        lambda: _derive_house_parameters(geo, house_profile, year),
        lambda params: params,
    )


def _derive_house_parameters(
    thermal: dict,
    house_profile: dict | None,
    year: int,
) -> ThermalParameters:
    from data.heating_need import (
        daily_electric_kwh,
        heating_params_from_thermal,
        specific_heating_kwh_m2,
    )
    from data.modeled_climate import reference_climate_for_thermal
    from optimizer.thermal_coupled import _group_hourly_by_day
    from optimizer.thermal_house import (
        _flat_ambient_from_day_rows,
        resolve_house_heat_loss_kw_per_k,
    )

    bundle, collector = reference_climate_for_thermal(
        thermal, house_profile=house_profile, year=year
    )
    params = heating_params_from_thermal(thermal)
    area_m2 = float(params.get("solar_thermal_area_m2", 0.0) or 0.0)
    hourly_wm2 = bundle.collector_surface_series(collector) if area_m2 > 0.0 else None
    daily = daily_electric_kwh(
        **params,
        hourly_temperature_c=bundle.temperature_c,
        hourly_collector_wm2=hourly_wm2,
    )
    living = float(params["living_area_m2"])
    if living <= 0.0:
        return ThermalParameters(year, round(sum(daily), 3), None, None)
    override = params.get("house_heat_loss_kw_per_k")
    # Same ambient series and calibration as house_year_result → one H per house.
    ambient = _flat_ambient_from_day_rows(
        _group_hourly_by_day(bundle.temperature_c, None, 0.0)
    )
    house_h = resolve_house_heat_loss_kw_per_k(
        override_kw_per_k=override,
        annual_heat_kwh=living
        * specific_heating_kwh_m2(params["building_class"], hwb_kwh_m2=params["hwb_kwh_m2"]),
        ambient_c=ambient,
        target_temp_c=params["target_temp_c"],
        heating_limit_c=params["heating_limit_c"],
    )
    return ThermalParameters(
        year,
        round(sum(daily), 3),
        float(house_h),
        SOURCE_OVERRIDE if override is not None else SOURCE_YEAR_SIM,
    )


def thermal_rc_parameters(
    consumer: dict,
    *,
    reference_year: int | None = None,
) -> ThermalParameters:
    """Annual electric kWh of a ``thermal_rc`` consumer (pool / SwimSpa)."""
    from data.open_meteo_solar_archive import last_full_archive_year
    from house_config.thermal_rc_profile import (
        _planning_timezone_for_rc,
        thermal_rc_params,
    )
    from optimizer.thermal_year_cache import THERMAL_PARAMETERS_CACHE, fingerprint_json

    rc = thermal_rc_params(consumer)
    year = reference_year if reference_year is not None else last_full_archive_year()
    key = (
        "thermal_rc",
        fingerprint_json(rc),
        consumer.get("nominal_power_kw"),
        _planning_timezone_for_rc(rc),
        year,
    )
    return THERMAL_PARAMETERS_CACHE.get_or_compute(
        key,
        lambda: _derive_thermal_rc_parameters(consumer, year),
        lambda params: params,
    )


def _derive_thermal_rc_parameters(consumer: dict, year: int) -> ThermalParameters:
    from house_config.thermal_rc_profile import estimate_thermal_rc_annual_kwh

    annual_kwh, ref_year = estimate_thermal_rc_annual_kwh(consumer, reference_year=year)
    return ThermalParameters(ref_year, float(annual_kwh), None, None)
