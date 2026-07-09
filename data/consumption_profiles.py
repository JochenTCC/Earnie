"""Synthetische Verbrauchsprofile aus Hausprofilen für Backtesting."""
from __future__ import annotations

from data.heating_need import hourly_profile_for_year, weekly_electric_kwh
from house_config.baseload import consumer_annual_kwh
from house_config.consumption_csv import load_hourly_profile_csv


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
        if consumer.get("type") == "thermal_annual":
            thermal = consumer.get("thermal") or {}
            weekly = weekly_electric_kwh(
                living_area_m2=float(thermal.get("living_area_m2", 0.0)),
                building_class=int(thermal.get("building_class", 3)),
                heat_pump_type=str(thermal.get("heat_pump_type", "luft")),
                persons=int(thermal.get("persons", 2)),
                latitude=float(thermal.get("latitude", 48.0)),
                longitude=float(thermal.get("longitude", 10.0)),
                target_temp_c=float(thermal.get("target_temp_c", 21.5)),
                heating_limit_c=float(thermal.get("heating_limit_c", 15.0)),
            )
            thermal_hourly = hourly_profile_for_year(weekly, hours_per_year=hours)
            hourly = [a + b for a, b in zip(hourly, thermal_hourly)]
            continue
        consumer_kwh = consumer_annual_kwh(consumer)
        add_kw = consumer_kwh / max(1, hours)
        hourly = [v + add_kw for v in hourly]
    return hourly
