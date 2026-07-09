"""Grundlast-Berechnung und Untergrenze (5 % des Jahresverbrauchs)."""
from __future__ import annotations

BASELOAD_MIN_FRACTION = 0.05


def consumer_annual_kwh(consumer: dict) -> float:
    if consumer.get("profile_csv"):
        return float(consumer.get("annual_kwh", 0.0) or 0.0)
    if consumer.get("type") == "thermal_annual":
        from data.heating_need import estimate_annual_kwh

        thermal = consumer.get("thermal") or {}
        hwb = thermal.get("hwb_kwh_m2")
        hwb_value = float(hwb) if hwb not in (None, "") else None
        return estimate_annual_kwh(
            living_area_m2=float(thermal.get("living_area_m2", 0.0)),
            building_class=int(thermal.get("building_class", 3)),
            heat_pump_type=str(thermal.get("heat_pump_type", "luft")),
            persons=int(thermal.get("persons", 2)),
            latitude=float(thermal.get("latitude", 48.0)),
            longitude=float(thermal.get("longitude", 10.0)),
            target_temp_c=float(thermal.get("target_temp_c", 21.5)),
            heating_limit_c=float(thermal.get("heating_limit_c", 15.0)),
            hwb_kwh_m2=hwb_value,
        )
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
