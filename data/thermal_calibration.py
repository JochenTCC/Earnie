"""Kalibrierung des Wärmeleitwerts U aus historischen Loxone-CSV-Logs."""
from __future__ import annotations

import math

import pandas as pd

from .loxone_csv_timeseries import load_hourly_series, load_power_hourly
from optimizer.thermal_model import capacity_kwh_per_k_from_volume


def _mark_stuck_hours(ist: pd.Series, min_flat_hours: int) -> pd.Series:
    flat = ist.rolling(min_flat_hours).apply(lambda x: 1 if len(set(x)) == 1 else 0, raw=True)
    return flat == 1


def estimate_heat_loss_kw_per_k(
    history_logs: dict,
    *,
    water_volume_liters: float,
    heating_power_threshold_kw: float,
    min_flat_hours: int = 12,
    min_samples: int = 20,
) -> tuple[float, dict]:
    """
    Schätzt U (kW/K) aus Abkühlphasen ohne Heizung.
    Returns (U, detail_dict).
    """
    actual_path = history_logs.get("actual_temp_csv", "")
    ambient_path = history_logs.get("ambient_temp_csv", "")
    power_path = history_logs.get("power_csv", "")
    if not actual_path or not ambient_path or not power_path:
        raise ValueError(
            "history_logs benötigt actual_temp_csv, ambient_temp_csv und power_csv für die Kalibrierung."
        )

    ist = load_hourly_series(actual_path)
    ambient = load_hourly_series(ambient_path)
    power = load_power_hourly(power_path)
    merged = pd.DataFrame({"ist": ist, "ambient": ambient, "power": power}).dropna()
    if merged.empty:
        raise ValueError("Keine überlappenden Stunden in den Historien-CSV-Dateien.")

    merged["stuck"] = _mark_stuck_hours(merged["ist"], min_flat_hours)
    merged = merged[~merged["stuck"]].copy()
    merged["dT"] = merged["ist"].diff()
    merged["dt_h"] = merged.index.to_series().diff().dt.total_seconds() / 3600.0
    cooling = merged[
        (merged["power"] < heating_power_threshold_kw)
        & (merged["dt_h"] == 1.0)
        & (merged["dT"] <= -0.25)
    ].copy()
    if cooling.empty:
        raise ValueError("Keine geeigneten Abkühlphasen für die U-Schätzung gefunden.")

    capacity = capacity_kwh_per_k_from_volume(water_volume_liters)
    cooling["deltaT"] = cooling["ist"] - cooling["ambient"]
    cooling = cooling[cooling["deltaT"] > 5.0]
    cooling["rate_k_per_h"] = cooling["dT"] / cooling["dt_h"]
    cooling["U"] = (-cooling["rate_k_per_h"] * capacity) / cooling["deltaT"]
    samples = cooling["U"][(cooling["U"] > 0) & (cooling["U"] < 1.0)]
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
    }
    return u_value, detail
