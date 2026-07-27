"""Jahres Verbrauch [kWh] — shared SE Gesamtkosten / Fake-Jahresrechnung source."""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

from simulation.engine import (
    HISTORICAL_REFERENCE_ID,
    SCENARIO_REFERENCE_PREFIX,
    is_scenario_reference_id,
)


def _parent_id_from_scenario_reference(scenario_id: str) -> str | None:
    if not is_scenario_reference_id(scenario_id):
        return None
    return str(scenario_id)[len(SCENARIO_REFERENCE_PREFIX) :]


def _totals_kwh(plausibility: dict, scenario_id: str, key: str) -> float | None:
    totals = (plausibility.get(scenario_id) or {}).get("consumption_totals") or {}
    value = totals.get(key)
    return None if value is None else float(value)


def historical_ref_kwh_for_period(
    cons_df: pd.DataFrame,
    period: dict,
) -> float | None:
    """Period sum of cons_data ``total_kw`` (SE Historisch Jahres Verbrauch)."""
    start_raw = period.get("start")
    end_raw = period.get("end")
    if not start_raw or not end_raw or cons_df is None or cons_df.empty:
        return None
    if "total_kw" not in cons_df.columns:
        return None
    start = datetime.combine(date.fromisoformat(str(start_raw)), time.min)
    end = datetime.combine(date.fromisoformat(str(end_raw)), time(23, 59, 59))
    sliced = cons_df.loc[(cons_df.index >= start) & (cons_df.index <= end)]
    if sliced.empty:
        return None
    return round(float(sliced["total_kw"].fillna(0.0).sum()), 1)


def jahres_verbrauch_kwh(
    scenario_id: str,
    *,
    reference_id: str = HISTORICAL_REFERENCE_ID,
    ref_kwh: float | None,
    plausibility: dict,
) -> float | None:
    """
    Same asymmetric sources as SE Gesamtkosten ``Jahres Verbrauch [kWh]``.

    - Historisch: period ``cons_data`` sum (``ref_kwh``)
    - Scenario reference (``ref:*``): parent window ``historical_kwh``
    - Optimized scenario: window ``optimized_kwh``
    """
    if scenario_id == reference_id:
        return None if ref_kwh is None else float(ref_kwh)
    parent_id = _parent_id_from_scenario_reference(scenario_id)
    if parent_id is not None:
        return _totals_kwh(plausibility, parent_id, "historical_kwh")
    return _totals_kwh(plausibility, scenario_id, "optimized_kwh")


def jahres_verbrauch_map(
    scenario_ids: list[str],
    *,
    reference_id: str = HISTORICAL_REFERENCE_ID,
    ref_kwh: float | None,
    plausibility: dict,
) -> dict[str, float]:
    """Non-null Jahres Verbrauch values keyed by result scenario id."""
    out: dict[str, float] = {}
    for scenario_id in scenario_ids:
        value = jahres_verbrauch_kwh(
            scenario_id,
            reference_id=reference_id,
            ref_kwh=ref_kwh,
            plausibility=plausibility,
        )
        if value is not None:
            out[scenario_id] = float(value)
    return out
