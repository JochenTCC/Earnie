"""Grundlast-Berechnung und Untergrenze (2 % des Jahresverbrauchs)."""
from __future__ import annotations

from house_config.consumption_csv import consumer_uses_profile_csv

BASELOAD_MIN_FRACTION = 0.02
# When trimming floor to match Ist vs Modell, never go below this share of Jahresverbrauch.
BASELOAD_TRIM_MIN_FRACTION = 0.01


def _config_ready_for_open_meteo() -> bool:
    """True when config.CONFIG is fully constructed (avoid circular import during Config())."""
    import sys

    cfg = sys.modules.get("config")
    if cfg is None:
        return False
    return getattr(cfg, "CONFIG", None) is not None and callable(
        getattr(cfg, "get_planning_timezone", None)
    )


def consumer_annual_kwh(consumer: dict) -> float:
    if consumer_uses_profile_csv(consumer):
        stored = float(consumer.get("annual_kwh", 0.0) or 0.0)
        if stored > 0.0:
            return stored
        path = str(consumer.get("profile_csv", "") or "").strip()
        if not path:
            return 0.0
        try:
            from house_config.consumption_csv import estimate_annual_kwh_from_profile_csv

            return estimate_annual_kwh_from_profile_csv(path)
        except (OSError, ValueError, FileNotFoundError):
            return 0.0
    if consumer.get("type") == "ev":
        from house_config.ev_profile import estimate_ev_annual_kwh

        return estimate_ev_annual_kwh(consumer)
    if consumer.get("type") == "thermal_annual":
        thermal = consumer.get("thermal") or consumer
        lat = thermal.get("latitude")
        lon = thermal.get("longitude")
        # Open-Meteo only after Config() finished — during profile normalize inside
        # Config.__init__, modeled_climate → config is a circular import.
        if lat is not None and lon is not None and _config_ready_for_open_meteo():
            from data.modeled_climate import thermal_annual_kwh_from_archive

            annual_kwh, _year = thermal_annual_kwh_from_archive(thermal)
            return annual_kwh
        from data.heating_need import estimate_annual_kwh, heating_params_from_thermal

        return estimate_annual_kwh(**heating_params_from_thermal(thermal))
    if consumer.get("type") == "generic":
        from house_config.generic_schedule import generic_annual_kwh

        return generic_annual_kwh(consumer)
    if consumer.get("type") == "thermal_rc":
        rc = consumer.get("thermal_rc") or consumer
        lat = rc.get("latitude")
        lon = rc.get("longitude")
        if lat is not None and lon is not None and _config_ready_for_open_meteo():
            from house_config.thermal_rc_profile import estimate_thermal_rc_annual_kwh

            annual_kwh, _year = estimate_thermal_rc_annual_kwh(consumer)
            return annual_kwh
        return float(consumer.get("annual_kwh", 0.0) or 0.0)
    return float(consumer.get("annual_kwh", 0.0) or 0.0)


def compute_baseload_kwh(
    annual_kwh: float,
    consumers: list[dict],
    *,
    min_fraction: float | None = None,
) -> dict:
    """Grundlast = max(floor × Jahresverbrauch, Jahresverbrauch − Σ Verbraucher)."""
    annual = float(annual_kwh)
    floor = BASELOAD_MIN_FRACTION if min_fraction is None else float(min_fraction)
    if floor < 0.0:
        raise ValueError(f"min_fraction must be >= 0, got {floor}")
    consumer_sum = sum(consumer_annual_kwh(c) for c in consumers)
    raw_baseload = max(0.0, annual - consumer_sum)
    min_baseload = annual * floor
    baseload = max(raw_baseload, min_baseload) if annual > 0 else 0.0
    return {
        "consumer_kwh": round(consumer_sum, 3),
        "baseload_kwh": round(baseload, 3),
        "baseload_min_kwh": round(min_baseload, 3),
        "raw_baseload_kwh": round(raw_baseload, 3),
        "floor_fraction": round(floor, 6),
    }


def trim_baseload_floor_to_match_ist(
    annual_kwh: float,
    consumers: list[dict],
    ist_annual_kwh: float,
    *,
    model_consumer_kwh: float | None = None,
    min_floor_fraction: float = BASELOAD_TRIM_MIN_FRACTION,
) -> dict:
    """Trim Grundlast so Modell ≈ Ist-Jahresverbrauch; floor never below ``min_floor_fraction``.

    Ideal baseload is ``ist − model_consumers`` (defaults to Σ consumer_annual_kwh).
    Resulting baseload is at least ``annual × min_floor_fraction`` (default 1 %).
    Does not apply the default 2 % floor when that would push Modell above Ist.
    """
    annual = float(annual_kwh)
    ist = float(ist_annual_kwh)
    floor = float(min_floor_fraction)
    if floor < BASELOAD_TRIM_MIN_FRACTION - 1e-12:
        raise ValueError(
            f"min_floor_fraction must be >= {BASELOAD_TRIM_MIN_FRACTION} "
            f"(1 %), got {floor}"
        )
    if model_consumer_kwh is None:
        consumer_sum = sum(consumer_annual_kwh(c) for c in consumers)
    else:
        consumer_sum = float(model_consumer_kwh)
    ideal = max(0.0, ist - consumer_sum)
    min_baseload = annual * floor if annual > 0 else 0.0
    baseload = max(ideal, min_baseload) if annual > 0 else 0.0
    effective_fraction = (baseload / annual) if annual > 0 else 0.0
    return {
        "consumer_kwh": round(consumer_sum, 3),
        "baseload_kwh": round(baseload, 3),
        "baseload_min_kwh": round(min_baseload, 3),
        "raw_baseload_kwh": round(ideal, 3),
        "floor_fraction": round(effective_fraction, 6),
        "ist_annual_kwh": round(ist, 3),
        "ideal_baseload_kwh": round(ideal, 3),
    }
