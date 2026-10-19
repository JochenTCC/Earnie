"""Grundlast-Berechnung und Untergrenze (2 % des Jahresverbrauchs)."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

from house_config.consumption_csv import consumer_uses_profile_csv

BASELOAD_MIN_FRACTION = 0.02
# Suggested Grundlast when consumers over-allocate the Jahresverbrauch (~150 W standby).
TYPICAL_BASELOAD_KWH = 1314.0
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


def _require_config_ready_for_climate(consumer: dict) -> None:
    """Fail loud when a weather-based annual kWh is requested before ``Config`` exists.

    The Open-Meteo chain (timezone, HTTP timeout) reads ``config``. During
    ``Config.__init__`` profiles are only normalized; the baseload is resolved
    lazily (``resolve_profile_baseload``) once ``Config`` is built. A request
    earlier than that must not silently fall back to a different estimate.
    """
    import sys

    cfg = sys.modules.get("config")
    if cfg is not None and getattr(cfg, "CONFIG", None) is not None:
        return
    raise RuntimeError(
        f"Jahresverbrauch von Verbraucher '{consumer.get('id') or consumer.get('label')}' "
        "(Wetterdaten) vor dem Config-Aufbau angefordert — Grundlast erst nach "
        "Config-Aufbau über resolve_profile_baseload()/profile_baseload_kwh() auflösen."
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
        if lat is not None and lon is not None:
            _require_config_ready_for_climate(consumer)
            from optimizer.thermal_parameters import house_thermal_parameters

            return house_thermal_parameters(thermal).annual_electric_kwh
        from data.heating_need import estimate_annual_kwh, heating_params_from_thermal

        return estimate_annual_kwh(**heating_params_from_thermal(thermal))
    if consumer.get("type") == "generic":
        from house_config.generic_schedule import generic_annual_kwh

        return generic_annual_kwh(consumer)
    if consumer.get("type") == "thermal_rc":
        rc = consumer.get("thermal_rc") or consumer
        lat = rc.get("latitude")
        lon = rc.get("longitude")
        if lat is not None and lon is not None:
            _require_config_ready_for_climate(consumer)
            from optimizer.thermal_parameters import thermal_rc_parameters

            return thermal_rc_parameters(consumer).annual_electric_kwh
        return float(consumer.get("annual_kwh", 0.0) or 0.0)
    return float(consumer.get("annual_kwh", 0.0) or 0.0)


def allocation_diagnostics(
    annual_kwh: float,
    consumer_kwh: float,
    *,
    floor_fraction: float = BASELOAD_MIN_FRACTION,
) -> dict:
    """Plausibility of Σ Verbraucher vs. Jahresverbrauch (no silent clamp).

    ``over_allocated``: Σ Verbraucher > Jahresverbrauch — baseload would be negative.
    ``baseload_floored``: Σ ≤ Jahresverbrauch, but the rest is below the minimum
    baseload, so the model total exceeds the Jahresverbrauch.
    Suggestions are ``None`` when the allocation is fine.
    """
    annual = float(annual_kwh)
    consumers = float(consumer_kwh)
    over_allocated = consumers > annual + 1e-9
    min_baseload = annual * floor_fraction if annual > 0 else 0.0
    baseload_floored = (
        not over_allocated and annual > 0 and (annual - consumers) < min_baseload - 1e-9
    )
    suggested_annual: float | None = None
    suggested_reduction: float | None = None
    if over_allocated or baseload_floored:
        needed = max(
            consumers + TYPICAL_BASELOAD_KWH,
            consumers / (1.0 - floor_fraction) if floor_fraction < 1.0 else consumers,
        )
        suggested_annual = float(math.ceil(needed / 10.0) * 10.0)
        suggested_reduction = round(
            max(0.0, consumers - max(0.0, annual - TYPICAL_BASELOAD_KWH)), 3
        )
    return {
        "over_allocated": over_allocated,
        "baseload_floored": baseload_floored,
        "shortfall_kwh": round(max(0.0, consumers - annual), 3),
        "suggested_annual_kwh": suggested_annual,
        "suggested_consumer_reduction_kwh": suggested_reduction,
    }


def compute_baseload_kwh(
    annual_kwh: float,
    consumers: list[dict],
    *,
    min_fraction: float | None = None,
) -> dict:
    """Grundlast = max(floor × Jahresverbrauch, Jahresverbrauch − Σ Verbraucher).

    The result also carries ``allocation_diagnostics`` (over-allocation flags and
    suggestions) — callers decide where to fail loud (see
    ``ensure_baseload_not_over_allocated``).
    """
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
        **allocation_diagnostics(annual, consumer_sum, floor_fraction=floor),
    }


_DERIVED_BASELOAD_KEYS = ("baseload_kwh", "consumer_kwh", "baseload_min_kwh")


def resolve_profile_baseload(profile: dict) -> dict:
    """Derive Grundlast fields of a normalized house profile (idempotent, in place).

    Normalization (``profiles_store``) deliberately does not compute them: they need
    weather data (Open-Meteo) and therefore a built ``Config``. Call this (or one of
    the ``profile_*_kwh`` accessors) at the point of use.
    """
    if all(key in profile for key in _DERIVED_BASELOAD_KEYS):
        return profile
    if "annual_kwh" not in profile or "consumers" not in profile:
        raise ValueError(
            "Hausprofil ohne annual_kwh/consumers — Grundlast nicht ableitbar "
            "(Profil über house_config.profiles_store normalisieren oder "
            "baseload_kwh/consumer_kwh/baseload_min_kwh explizit setzen)."
        )
    result = compute_baseload_kwh(profile["annual_kwh"], profile["consumers"])
    for key in _DERIVED_BASELOAD_KEYS:
        profile.setdefault(key, result[key])  # explicit values (fixtures) win
    return profile


def profile_baseload_kwh(profile: dict) -> float:
    """Grundlast (kWh/a) of a house profile; derived on first use."""
    if "baseload_kwh" in profile:
        return float(profile["baseload_kwh"])
    return float(resolve_profile_baseload(profile)["baseload_kwh"])


def profile_consumer_kwh(profile: dict) -> float:
    """Σ Verbraucher (kWh/a) of a house profile; derived on first use."""
    if "consumer_kwh" in profile:
        return float(profile["consumer_kwh"])
    return float(resolve_profile_baseload(profile)["consumer_kwh"])


class BaseloadOverAllocatedError(ValueError):
    """Σ Verbraucher exceeds the Jahresverbrauch of a house profile."""


def baseload_allocation_message(
    annual_kwh: float,
    consumer_kwh: float,
    *,
    profile_label: str = "",
    floor_fraction: float = BASELOAD_MIN_FRACTION,
) -> str | None:
    """German warning text with suggestions, or ``None`` when the allocation is fine."""
    diag = allocation_diagnostics(
        annual_kwh, consumer_kwh, floor_fraction=floor_fraction
    )
    if not (diag["over_allocated"] or diag["baseload_floored"]):
        return None
    name = f"Hausprofil '{profile_label}': " if profile_label else ""
    if diag["over_allocated"]:
        head = (
            f"{name}Die Summe der Verbraucher ({consumer_kwh:.0f} kWh/a) ist größer als "
            f"der Jahresverbrauch ({annual_kwh:.0f} kWh/a) — es bleibt keine Grundlast übrig "
            f"(Differenz {diag['shortfall_kwh']:.0f} kWh/a)."
        )
    else:
        head = (
            f"{name}Zwischen Jahresverbrauch ({annual_kwh:.0f} kWh/a) und Summe der "
            f"Verbraucher ({consumer_kwh:.0f} kWh/a) bleibt weniger als die Mindest-Grundlast "
            f"von {floor_fraction:.0%} übrig — das Modell liegt über dem Jahresverbrauch."
        )
    return (
        f"{head} Entweder die Verbraucher um ca. "
        f"{diag['suggested_consumer_reduction_kwh']:.0f} kWh/a reduzieren oder den "
        f"Jahresverbrauch / die Grundlast erhöhen. Vorschlag: Jahresverbrauch "
        f"≥ {diag['suggested_annual_kwh']:.0f} kWh/a "
        f"(Verbraucher + typische Grundlast von {TYPICAL_BASELOAD_KWH:.0f} kWh/a)."
    )


def ensure_baseload_not_over_allocated(profile: dict, *, context: str = "") -> None:
    """Raise ``BaseloadOverAllocatedError`` when Σ Verbraucher > Jahresverbrauch.

    ``profile`` is a normalized house profile; ``consumer_kwh`` is derived on first
    use. The softer ``baseload_floored`` case is not an error; use
    ``baseload_allocation_message`` to show it as a warning.
    """
    consumer = profile_consumer_kwh(profile)
    annual = float(profile["annual_kwh"])
    if not allocation_diagnostics(annual, consumer)["over_allocated"]:
        return
    message = baseload_allocation_message(
        annual, consumer, profile_label=str(profile.get("label") or profile.get("id") or "")
    )
    prefix = f"{context}: " if context else ""
    raise BaseloadOverAllocatedError(f"{prefix}{message}")


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
