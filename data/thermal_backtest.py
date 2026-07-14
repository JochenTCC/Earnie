"""Historischer Abgleich des thermischen RC-Modells gegen geloggte Ist-Temperaturen."""
from __future__ import annotations

import math

import pandas as pd

from data.thermal_power import load_thermal_history_merged


def load_merged_history(
    history_logs: dict,
    *,
    heating_threshold_kw: float = 2.0,
    filter_nominal_kw: float = 0.18,
) -> pd.DataFrame:
    """Stündliche Ist-, Außen- und Leistungsdaten aus thermal_control.history_logs."""
    return load_thermal_history_merged(
        history_logs,
        heating_threshold_kw=heating_threshold_kw,
        filter_nominal_kw=filter_nominal_kw,
    )


def backtest_heat_loss_kw_per_k(
    merged: pd.DataFrame,
    *,
    water_volume_liters: float,
    heating_power_threshold_kw: float,
    heat_loss_kw_per_k: float,
    heating_efficiency: float,
    min_flat_hours: int = 12,
) -> dict:
    """
    Simuliert Ist-Temp. stündlich (Start = gemessene Ist-Temp.) und vergleicht mit Log.
    """
    from optimizer.thermal_model import capacity_kwh_per_k_from_volume, simulate_next_temp_c

    if heat_loss_kw_per_k < 0:
        raise ValueError("heat_loss_kw_per_k muss >= 0 sein.")
    capacity = capacity_kwh_per_k_from_volume(water_volume_liters)
    data = merged.copy()
    if "heating_kw" not in data.columns:
        data["heating_kw"] = data["power_kw"].where(
            data["power_kw"] >= heating_power_threshold_kw,
            0.0,
        )
    data["stuck"] = _mark_stuck_hours(data["ist_c"], min_flat_hours)
    data = data[~data["stuck"]].copy()
    if data.empty:
        raise ValueError("Nach stuck-Filter keine Historien-Stunden übrig.")

    sim_temps: list[float] = []
    errors: list[float] = []
    index = data.index.to_list()
    for i, ts in enumerate(index):
        row = data.loc[ts]
        if i == 0:
            sim = float(row["ist_c"])
        else:
            prev_ts = index[i - 1]
            gap_h = (ts - prev_ts).total_seconds() / 3600.0
            if gap_h != 1.0:
                sim = float(row["ist_c"])
            else:
                heat_kw = float(row["heating_kw"])
                prev_ambient = float(data.loc[prev_ts, "ambient_c"])
                sim = simulate_next_temp_c(
                    sim_temps[-1],
                    prev_ambient,
                    heat_kw,
                    capacity_kwh_per_k=capacity,
                    heat_loss_kw_per_k=heat_loss_kw_per_k,
                    heating_efficiency=heating_efficiency,
                )
        sim_temps.append(sim)
        errors.append(sim - float(row["ist_c"]))

    err_series = pd.Series(errors, index=index)
    abs_err = err_series.abs()
    result = {
        "hours": int(len(data)),
        "mae_c": round(float(abs_err.mean()), 3),
        "rmse_c": round(float(math.sqrt((err_series**2).mean())), 3),
        "max_abs_error_c": round(float(abs_err.max()), 3),
        "hours_abs_error_ge_1c": int((abs_err >= 1.0).sum()),
    }
    if merged.attrs.get("heating_attribution"):
        result["heating_attribution"] = merged.attrs["heating_attribution"]
    return result


def _mark_stuck_hours(ist: pd.Series, min_flat_hours: int) -> pd.Series:
    flat = ist.rolling(min_flat_hours).apply(lambda x: 1 if len(set(x)) == 1 else 0, raw=True)
    return flat == 1
