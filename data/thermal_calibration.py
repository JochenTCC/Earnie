"""Kalibrierung des Wärmeleitwerts U aus historischen Loxone-CSV-Logs."""
from __future__ import annotations

import math

import pandas as pd

from data.thermal_power import load_thermal_history_merged
from optimizer.thermal_model import capacity_kwh_per_k_from_volume


def _mark_stuck_hours(ist: pd.Series, min_flat_hours: int) -> pd.Series:
    flat = ist.rolling(min_flat_hours).apply(lambda x: 1 if len(set(x)) == 1 else 0, raw=True)
    return flat == 1


def estimate_heat_loss_kw_per_k(
    history_logs: dict,
    *,
    water_volume_liters: float,
    heating_power_threshold_kw: float,
    filter_nominal_kw: float = 0.18,
    min_flat_hours: int = 12,
    min_samples: int = 20,
) -> tuple[float, dict]:
    """
    Schätzt U (kW/K) aus Abkühlphasen ohne Heizung.
    Returns (U, detail_dict).
    """
    merged = load_thermal_history_merged(
        history_logs,
        heating_threshold_kw=heating_power_threshold_kw,
        filter_nominal_kw=filter_nominal_kw,
    )
    attribution = merged.attrs.get("heating_attribution", "threshold")

    merged["stuck"] = _mark_stuck_hours(merged["ist_c"], min_flat_hours)
    merged = merged[~merged["stuck"]].copy()
    merged["dT"] = merged["ist_c"].diff()
    merged["dt_h"] = merged.index.to_series().diff().dt.total_seconds() / 3600.0
    if attribution == "indicator":
        idle_mask = merged["heating_kw"] <= 0.0
    else:
        idle_mask = merged["power_kw"] < heating_power_threshold_kw
    hourly = merged[idle_mask & (merged["dt_h"] == 1.0)].copy()
    if hourly.empty:
        raise ValueError("Keine geeigneten Ruhephasen für die U-Schätzung gefunden.")

    capacity = capacity_kwh_per_k_from_volume(water_volume_liters)
    hourly["rate_k_per_h"] = hourly["dT"] / hourly["dt_h"]

    cooling = hourly[hourly["dT"] <= -0.25].copy()
    cooling["deltaT"] = cooling["ist_c"] - cooling["ambient_c"]
    cooling = cooling[cooling["deltaT"] > 5.0]
    cooling["U"] = (-cooling["rate_k_per_h"] * capacity) / cooling["deltaT"]

    warming = hourly[hourly["dT"] >= 0.25].copy()
    warming["deltaT"] = warming["ambient_c"] - warming["ist_c"]
    warming = warming[warming["deltaT"] > 5.0]
    warming["U"] = (warming["rate_k_per_h"] * capacity) / warming["deltaT"]

    samples = pd.concat([cooling["U"], warming["U"]], ignore_index=True)
    samples = samples[(samples > 0) & (samples < 1.0)]
    if len(samples) < min_samples:
        raise ValueError(
            f"Zu wenige U-Stichproben ({len(samples)}); mindestens {min_samples} erforderlich."
        )

    u_value = float(samples.median())
    if not math.isfinite(u_value) or u_value <= 0:
        raise ValueError("U-Schätzung ist nicht endlich oder <= 0.")

    detail = {
        "samples": int(len(samples)),
        "u_median_kw_per_k": round(u_value, 5),
        "u_p25_kw_per_k": round(float(samples.quantile(0.25)), 5),
        "u_p75_kw_per_k": round(float(samples.quantile(0.75)), 5),
        "merged_hours": int(len(merged)),
        "cooling_events": int(len(cooling)),
        "warming_events": int(len(warming)),
        "heating_attribution": attribution,
    }
    return u_value, detail
