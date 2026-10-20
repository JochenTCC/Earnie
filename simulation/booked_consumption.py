"""Booked SE consumption per result series — one source for Gesamtkosten, invoices, plausibility.

"Booked" = the hourly/QH result series that also carries costs, import and export
(``backtesting.csv``). Each slot counts once (duplicate timestamps from overlapping
book windows are collapsed, the later row wins). Battery standby is part of the
MILP's ``Verbrauch-Prognose`` (and therefore of ``consumption_kw``) but is reported
separately, not as house consumption.
"""
from __future__ import annotations

import pandas as pd

from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h

BOOKED_CONSUMPTION_KEY = "booked_consumption"

_NON_CONSUMER_KW_COLUMNS = frozenset(
    {"consumption_kw", "baseload_kw", "pv_kw", "batt_action_kw"}
)


def _naive_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    return index


def _unique_slots(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Rows with one entry per timestamp (last wins) and the number of dropped duplicates."""
    frame = df.copy()
    frame.index = _naive_index(df)
    duplicated = frame.index.duplicated(keep="last")
    return frame.loc[~duplicated], int(duplicated.sum())


def booked_consumption_totals(df: pd.DataFrame, *, standby_kw: float) -> dict:
    """Σ booked consumption (kWh) over unique slots; battery standby separately.

    ``standby_kw`` is the AC standby the MILP adds to every slot of an optimized
    scenario (0 for references / Historisch).
    """
    if df is None or df.empty:
        raise ValueError("Gebuchte Verbrauchsreihe ist leer.")
    if "consumption_kw" not in df.columns:
        raise ValueError("Gebuchte Verbrauchsreihe ohne Spalte consumption_kw.")
    if standby_kw < 0:
        raise ValueError(f"standby_kw muss >= 0 sein (got {standby_kw}).")
    dt_h = validate_dt_h(DEFAULT_DT_H)
    unique, duplicates = _unique_slots(df)
    slots = len(unique)
    total_kwh = float(unique["consumption_kw"].fillna(0.0).sum()) * dt_h
    standby_kwh = float(standby_kw) * slots * dt_h
    components: dict[str, float] = {}
    if "baseload_kw" in unique.columns:
        raw = {
            "baseload": float(unique["baseload_kw"].fillna(0.0).sum()) * dt_h
            - standby_kwh
        }
        for col in unique.columns:
            if not col.endswith("_kw") or col in _NON_CONSUMER_KW_COLUMNS:
                continue
            raw[col[: -len("_kw")]] = float(unique[col].fillna(0.0).sum()) * dt_h
        # known generics / appliance traces are peeled into consumption_kw only
        other = total_kwh - standby_kwh - sum(raw.values())
        if abs(other) >= 0.05:
            raw["other"] = other
        components = {key: round(value, 1) for key, value in raw.items()}
    return {
        "consumption_kwh": round(total_kwh - standby_kwh, 1),
        "standby_kwh": round(standby_kwh, 1),
        "slots": slots,
        "duplicate_slots": duplicates,
        "first_ts": unique.index.min().isoformat(),
        "last_ts": unique.index.max().isoformat(),
        "components_kwh": components,
    }


def slot_coverage_diff(scenario_df: pd.DataFrame, reference_df: pd.DataFrame) -> dict:
    """Slots booked only by the scenario resp. only by its reference (unique timestamps)."""
    scenario_slots = set(_naive_index(scenario_df))
    reference_slots = set(_naive_index(reference_df))
    return {
        "only_scenario_slots": len(scenario_slots - reference_slots),
        "only_reference_slots": len(reference_slots - scenario_slots),
    }


def booked_consumption_by_result(
    results: dict[str, pd.DataFrame],
    *,
    standby_kw_by_result: dict[str, float],
    reference_by_scenario: dict[str, str],
) -> dict[str, dict]:
    """Booked totals for every result id; optimized ids get the slot diff to their reference."""
    missing = [sid for sid in results if sid not in standby_kw_by_result]
    if missing:
        raise ValueError(
            "standby_kw fehlt für Ergebnis-IDs: " + ", ".join(sorted(missing))
        )
    out: dict[str, dict] = {}
    for sid, df in results.items():
        out[sid] = booked_consumption_totals(df, standby_kw=standby_kw_by_result[sid])
    for sid, ref_id in reference_by_scenario.items():
        if sid not in results or ref_id not in results:
            continue
        out[sid]["reference_coverage"] = {
            "reference_id": ref_id,
            **slot_coverage_diff(results[sid], results[ref_id]),
        }
    return out
