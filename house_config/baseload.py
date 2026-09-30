"""Grundlast-Berechnung und Untergrenze (2 % des Jahresverbrauchs)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from house_config.consumption_csv import consumer_uses_profile_csv

BASELOAD_MIN_FRACTION = 0.02
# When trimming floor to match Ist vs Modell, never go below this share of Jahresverbrauch.
BASELOAD_TRIM_MIN_FRACTION = 0.01

BASELOAD_DIST_EQUAL = "equal"
BASELOAD_DIST_MONTHLY = "monthly"
BASELOAD_DIST_VALUES = frozenset({BASELOAD_DIST_EQUAL, BASELOAD_DIST_MONTHLY})


def normalize_baseload_distribution(raw: object) -> str:
    value = str(raw or BASELOAD_DIST_EQUAL).strip().lower()
    return value if value in BASELOAD_DIST_VALUES else BASELOAD_DIST_EQUAL


def baseload_month_key(ts_raw: str | datetime) -> str:
    if isinstance(ts_raw, datetime):
        return f"{ts_raw.year}-{ts_raw.month:02d}"
    ts = datetime.fromisoformat(str(ts_raw).replace(" ", "T", 1)[:19])
    return f"{ts.year}-{ts.month:02d}"


def monthly_aligned_baseload_kw(
    timestamps: list[str],
    ist_kw: list[float],
    consumer_kw: list[float],
) -> list[float]:
    """Per-month residual baseload (kW): max(0, Ist_m − Cons_m) / hours_in_m."""
    n = len(timestamps)
    if n != len(ist_kw) or n != len(consumer_kw):
        raise ValueError(
            f"Length mismatch: timestamps={n}, ist_kw={len(ist_kw)}, "
            f"consumer_kw={len(consumer_kw)}"
        )
    if n == 0:
        return []
    ist_sum: dict[str, float] = defaultdict(float)
    cons_sum: dict[str, float] = defaultdict(float)
    hours: dict[str, int] = defaultdict(int)
    keys = [baseload_month_key(ts) for ts in timestamps]
    for key, ist, cons in zip(keys, ist_kw, consumer_kw):
        ist_sum[key] += float(ist)
        cons_sum[key] += float(cons)
        hours[key] += 1
    month_kw = {
        key: max(0.0, ist_sum[key] - cons_sum[key]) / hours[key]
        for key in hours
    }
    return [month_kw[key] for key in keys]


def monthly_baseload_kw_by_month(
    timestamps: list[str],
    ist_kw: list[float],
    consumer_kw: list[float],
) -> dict[str, float]:
    """YYYY-MM → constant baseload kW for that month."""
    series = monthly_aligned_baseload_kw(timestamps, ist_kw, consumer_kw)
    return {
        baseload_month_key(ts): float(kw)
        for ts, kw in zip(timestamps, series)
    }


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
        thermal = dict(consumer.get("thermal") or consumer)
        if "nominal_power_kw" not in thermal:
            thermal["nominal_power_kw"] = float(consumer.get("nominal_power_kw", 3.0) or 3.0)
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
