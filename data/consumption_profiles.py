"""Synthetische Verbrauchsprofile aus Hausprofilen für Backtesting."""
from __future__ import annotations

from datetime import date, timedelta

from data.heating_need import (
    heating_params_from_thermal,
    hourly_profile_for_year,
    weekly_electric_kwh,
)
from house_config.baseload import consumer_annual_kwh
from house_config.consumption_csv import load_hourly_profile_csv
from house_config.ev_profile import ev_hourly_kw_for_day


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


def build_modeled_hourly_kw_profile(profile: dict, *, hours: int = 8760) -> list[float]:
    """Modelliertes Profil aus Verbrauchern — ignoriert total_profile_csv."""
    annual = float(profile.get("annual_kwh", 0.0) or 0.0)
    baseload_kwh = float(profile.get("baseload_kwh", 0.0) or 0.0)
    baseload_kw = baseload_kwh / max(1, hours)
    hourly = [baseload_kw] * hours

    for consumer in profile.get("consumers", []):
        if consumer.get("profile_csv"):
            series = load_hourly_profile_csv(consumer["profile_csv"])
            for index, (_, kw) in enumerate(series):
                if index >= hours:
                    break
                hourly[index] += kw
            continue
        if consumer.get("type") == "ev":
            start_day = date(2023, 1, 1)
            for hour_index in range(hours):
                day = start_day + timedelta(days=hour_index // 24)
                day_hourly = ev_hourly_kw_for_day(consumer, day)
                hourly[hour_index] += day_hourly[hour_index % 24]
            continue
        if consumer.get("type") == "thermal_annual":
            thermal = consumer.get("thermal") or consumer
            weekly = weekly_electric_kwh(**heating_params_from_thermal(thermal))
            thermal_hourly = hourly_profile_for_year(weekly, hours_per_year=hours)
            hourly = [a + b for a, b in zip(hourly, thermal_hourly)]
            continue
        if consumer.get("type") == "generic" and consumer.get("schedule"):
            from house_config.generic_schedule import generic_hourly_kw_for_day

            start_day = date(2023, 1, 1)
            for hour_index in range(hours):
                day = start_day + timedelta(days=hour_index // 24)
                day_hourly = generic_hourly_kw_for_day(consumer, day)
                hourly[hour_index] += day_hourly[hour_index % 24]
            continue
        consumer_kwh = consumer_annual_kwh(consumer)
        add_kw = consumer_kwh / max(1, hours)
        hourly = [v + add_kw for v in hourly]
    return hourly
