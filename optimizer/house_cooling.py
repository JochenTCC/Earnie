"""Electricity of the house's air conditioning (cooling side of the house RC year model).

The cooling load is a fixed household load next to the heating: it is never part of the heat
source's daily input (``daily_electric_kwh`` feeds heat, fuel and the MILP heating target), it
is not planned flexibly (Live control is a backlog follow-up) and it is taken out of the
Grundlast like any other modeled consumer. Its hours come from the same house RC run as the
heating (``house_year_for_params`` with ``cooling``), so window and internal gains drive it.
"""
from __future__ import annotations

from datetime import datetime

from house_config.house_cooling import COOLING_KEY, cooling_consumer, cooling_id
from house_config.house_thermal import HEATING_ENABLED_KEY


def _thermal_of(consumer: dict) -> dict:
    """Nested ``thermal`` of a normalized consumer, or the flat Hauskonfigurator preview row."""
    return consumer.get("thermal") or consumer


def cooling_params(consumer: dict, profile: dict) -> dict:
    """House-year parameters of the cooling run (heating booked only with its switch on)."""
    from data.heating_need import heating_params_from_thermal
    from house_config.heating_systems import consumer_input_power_kw

    params = heating_params_from_thermal(_thermal_of(consumer))
    if "hp_electric_kw" not in params:
        params["hp_electric_kw"] = consumer_input_power_kw(consumer)
    params["cooling"] = consumer[COOLING_KEY]
    params["heating_booked"] = bool(profile.get(HEATING_ENABLED_KEY))
    return params


def cooling_year_hourly_kw(
    consumer: dict,
    profile: dict,
    *,
    bundle,
    collector,
    house_heat_loss_kw_per_k: float | None = None,
) -> list[float]:
    """Hourly cooling electricity (kW) for the weather of ``bundle``.

    ``house_heat_loss_kw_per_k`` pins H (calibrated on the reference year) for other years.
    """
    from data.heating_need import house_year_for_params
    from optimizer.house_gains import thermal_climate_kwargs

    params = cooling_params(consumer, profile)
    if house_heat_loss_kw_per_k is not None and params.get("house_heat_loss_kw_per_k") is None:
        params["house_heat_loss_kw_per_k"] = float(house_heat_loss_kw_per_k)
    climate = thermal_climate_kwargs(bundle, _thermal_of(consumer), collector)
    return list(house_year_for_params(**params, **climate).hourly_cooling_electric_kw)


def _reference_year_hourly_kw(consumer: dict, profile: dict) -> list[float]:
    """Cooling kW over the reference archive year (the modeled profile year)."""
    import config as _cfg

    if getattr(_cfg, "CONFIG", None) is None:
        raise RuntimeError(
            "Klimaanlagen-Profil vor dem Config-Aufbau angefordert "
            f"(Hausprofil '{profile.get('id')}')."
        )
    from data.modeled_climate import reference_climate_for_thermal
    from data.open_meteo_solar_archive import last_full_archive_year

    bundle, collector = reference_climate_for_thermal(
        _thermal_of(consumer), house_profile=profile, year=last_full_archive_year()
    )
    return cooling_year_hourly_kw(consumer, profile, bundle=bundle, collector=collector)


def cooling_annual_electric_kwh(profile: dict) -> float:
    """Annual electricity of the air conditioning (0 with „Kühlung betrachten“ off)."""
    consumer = cooling_consumer(profile)
    if consumer is None:
        return 0.0
    return round(float(sum(_reference_year_hourly_kw(consumer, profile))), 3)


def cooling_kw_for_slots(
    profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate=None,
) -> list[float]:
    """Cooling kW per slot: the slot's own weather with ``climate``, else the reference year."""
    consumer = cooling_consumer(profile)
    if consumer is None:
        return [0.0] * len(slot_datetimes)
    if climate is not None:
        return [climate.cooling_kw_at(consumer, profile, slot_dt) for slot_dt in slot_datetimes]
    from data.consumption_profiles import _modeled_hour_index

    year = _reference_year_hourly_kw(consumer, profile)
    out: list[float] = []
    for slot_dt in slot_datetimes:
        idx = _modeled_hour_index(slot_dt)
        out.append(float(year[idx]) if idx < len(year) else 0.0)
    return out


def cooling_modeled_hourly_kw(profile: dict, *, hours: int) -> dict[str, list[float]]:
    """``{<heating id>_cooling: kW per hour}`` of the modeled profile year (empty without cooling)."""
    consumer = cooling_consumer(profile)
    if consumer is None:
        return {}
    year = _reference_year_hourly_kw(consumer, profile)
    series = (year + [0.0] * hours)[:hours]
    return {cooling_id(consumer): series}
