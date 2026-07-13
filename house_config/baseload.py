"""Grundlast-Berechnung und Untergrenze (5 % des Jahresverbrauchs)."""
from __future__ import annotations

BASELOAD_MIN_FRACTION = 0.05


def _config_ready_for_open_meteo() -> bool:
    import config as cfg

    return getattr(cfg, "CONFIG", None) is not None and hasattr(cfg, "get_planning_timezone")


def consumer_annual_kwh(consumer: dict) -> float:
    if consumer.get("profile_csv"):
        return float(consumer.get("annual_kwh", 0.0) or 0.0)
    if consumer.get("type") == "ev":
        from house_config.ev_profile import estimate_ev_annual_kwh

        return estimate_ev_annual_kwh(consumer)
    if consumer.get("type") == "thermal_annual":
        thermal = consumer.get("thermal") or consumer
        lat = thermal.get("latitude")
        lon = thermal.get("longitude")
        if lat is not None and lon is not None and _config_ready_for_open_meteo():
            from data.modeled_climate import thermal_annual_kwh_from_archive

            annual_kwh, _year = thermal_annual_kwh_from_archive(thermal)
            return annual_kwh
        from data.heating_need import estimate_annual_kwh, heating_params_from_thermal

        return estimate_annual_kwh(**heating_params_from_thermal(thermal))
    if consumer.get("type") == "generic":
        from house_config.generic_schedule import generic_annual_kwh

        return generic_annual_kwh(consumer)
    return float(consumer.get("annual_kwh", 0.0) or 0.0)


def compute_baseload_kwh(annual_kwh: float, consumers: list[dict]) -> dict:
    """Grundlast = max(5 % Jahresverbrauch, Jahresverbrauch − Σ Verbraucher)."""
    annual = float(annual_kwh)
    consumer_sum = sum(consumer_annual_kwh(c) for c in consumers)
    raw_baseload = max(0.0, annual - consumer_sum)
    min_baseload = annual * BASELOAD_MIN_FRACTION
    baseload = max(raw_baseload, min_baseload) if annual > 0 else 0.0
    return {
        "consumer_kwh": round(consumer_sum, 3),
        "baseload_kwh": round(baseload, 3),
        "baseload_min_kwh": round(min_baseload, 3),
        "raw_baseload_kwh": round(raw_baseload, 3),
    }
