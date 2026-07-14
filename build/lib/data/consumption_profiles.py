"""Synthetische Verbrauchsprofile aus Hausprofilen für Backtesting."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

MODELED_PROFILE_REF_START = datetime(2023, 1, 1)
MODELED_PROFILE_HOURS_PER_YEAR = 8760

from data.heating_need import (
    daily_electric_kwh,
    heating_params_from_thermal,
    hourly_profile_for_year,
    thermal_daily_pwm_hourly_profile,
    weekly_electric_kwh,
)
from house_config.baseload import consumer_annual_kwh
from house_config.consumption_csv import load_hourly_profile_csv
from house_config.ev_profile import ev_hourly_kw_for_day

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext


def build_hourly_kw_profile(profile: dict, *, hours: int = 8760) -> list[float]:
    """
    Erzeugt stündliches kW-Profil: Grundlast + Verbraucher-Anteile gleichmäßig verteilt.
    Bei total_profile_csv wird diese Datei bevorzugt.
    """
    csv_path = profile.get("total_profile_csv", "")
    if csv_path:
        series = load_hourly_profile_csv(csv_path)
        values = [kw for _, kw in series]
        if len(values) >= hours:
            return values[:hours]
        pad = values[-1] if values else 0.0
        return values + [pad] * (hours - len(values))

    return build_modeled_hourly_kw_profile(profile, hours=hours)


def _consumer_id(consumer: dict, fallback_index: int) -> str:
    cid = consumer.get("id") or consumer.get("label")
    if cid:
        return str(cid)
    return f"consumer_{fallback_index}"


def _modeled_hour_index(slot_dt: datetime) -> int:
    naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
    return (
        int((naive - MODELED_PROFILE_REF_START).total_seconds() // 3600)
        % MODELED_PROFILE_HOURS_PER_YEAR
    )


def modeled_consumer_kw_at_datetime(
    consumer: dict,
    slot_dt: datetime,
    *,
    climate: ModeledClimateContext | None = None,
) -> float:
    """kW für einen Verbraucher zum Kalenderzeitpunkt (wie Backtesting-Overlay)."""
    if climate is not None and consumer.get("type") == "thermal_annual":
        return climate.thermal_consumer_kw_at(consumer, slot_dt)
    if consumer.get("profile_csv"):
        series = load_hourly_profile_csv(consumer["profile_csv"])
        hour_index = _modeled_hour_index(slot_dt)
        if hour_index < len(series):
            return float(series[hour_index][1])
        return 0.0
    if consumer.get("type") == "ev":
        naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
        day_hourly = ev_hourly_kw_for_day(consumer, naive.date())
        return float(day_hourly[naive.hour])
    if consumer.get("type") == "thermal_annual":
        profile = _modeled_consumer_hourly_kw(
            consumer,
            hours=MODELED_PROFILE_HOURS_PER_YEAR,
        )
        return float(profile[_modeled_hour_index(slot_dt)])
    if consumer.get("type") == "generic" and consumer.get("schedule"):
        from house_config.generic_schedule import generic_hourly_kw_for_day

        naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
        day_hourly = generic_hourly_kw_for_day(consumer, naive.date())
        return float(day_hourly[naive.hour])
    consumer_kwh = consumer_annual_kwh(consumer)
    return consumer_kwh / MODELED_PROFILE_HOURS_PER_YEAR


def _modeled_consumer_hourly_kw(consumer: dict, *, hours: int) -> list[float]:
    hourly = [0.0] * hours
    if consumer.get("profile_csv"):
        series = load_hourly_profile_csv(consumer["profile_csv"])
        for index, (_, kw) in enumerate(series):
            if index >= hours:
                break
            hourly[index] = float(kw)
        return hourly
    if consumer.get("type") == "ev":
        start_day = date(2023, 1, 1)
        for hour_index in range(hours):
            day = start_day + timedelta(days=hour_index // 24)
            day_hourly = ev_hourly_kw_for_day(consumer, day)
            hourly[hour_index] = day_hourly[hour_index % 24]
        return hourly
    if consumer.get("type") == "thermal_annual":
        thermal = consumer.get("thermal") or consumer
        daily = daily_electric_kwh(**heating_params_from_thermal(thermal))
        nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
        if nominal > 0.0:
            return thermal_daily_pwm_hourly_profile(
                daily,
                nominal_power_kw=nominal,
                hours_per_year=hours,
            )
        weekly = weekly_electric_kwh(**heating_params_from_thermal(thermal))
        return hourly_profile_for_year(weekly, hours_per_year=hours)
    if consumer.get("type") == "generic" and consumer.get("schedule"):
        from house_config.generic_schedule import generic_hourly_kw_for_day

        start_day = date(2023, 1, 1)
        for hour_index in range(hours):
            day = start_day + timedelta(days=hour_index // 24)
            day_hourly = generic_hourly_kw_for_day(consumer, day)
            hourly[hour_index] = day_hourly[hour_index % 24]
        return hourly
    consumer_kwh = consumer_annual_kwh(consumer)
    add_kw = consumer_kwh / max(1, hours)
    return [add_kw] * hours


def build_modeled_hourly_kw_by_consumer(
    profile: dict,
    *,
    hours: int = 8760,
) -> dict[str, list[float]]:
    """Stündliche kW je Verbraucher; Key ``baseload`` für Grundlast."""
    baseload_kwh = float(profile.get("baseload_kwh", 0.0) or 0.0)
    baseload_kw = baseload_kwh / max(1, hours)
    result: dict[str, list[float]] = {"baseload": [baseload_kw] * hours}
    for index, consumer in enumerate(profile.get("consumers", [])):
        result[_consumer_id(consumer, index)] = _modeled_consumer_hourly_kw(
            consumer,
            hours=hours,
        )
    return result


def build_modeled_hourly_kw_profile(profile: dict, *, hours: int = 8760) -> list[float]:
    """Modelliertes Profil aus Verbrauchern — ignoriert total_profile_csv."""
    by_consumer = build_modeled_hourly_kw_by_consumer(profile, hours=hours)
    hourly = [0.0] * hours
    for series in by_consumer.values():
        hourly = [a + b for a, b in zip(hourly, series)]
    return hourly
