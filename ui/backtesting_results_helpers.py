"""Hilfsfunktionen für Backtesting-Ergebnisanzeige (Perioden, Kostentabelle)."""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

import config
from scripts.run_backtesting import BACKTESTING_YEAR
from simulation.engine import HISTORICAL_REFERENCE_ID
from ui.consumption_validation_charts import cons_data_monthly_kwh

_DASH = "—"


def is_single_month_test_run(period: dict) -> bool:
    start_month = period.get("start_month")
    end_month = period.get("end_month")
    if start_month is None or end_month is None:
        return False
    return int(start_month) == int(end_month)


def format_test_run_caption(period: dict) -> str | None:
    if not is_single_month_test_run(period):
        return None
    month = int(period["start_month"])
    year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
    return f"Testlauf — nur Monat {month:02d}/{year}"


def nav_bounds_from_period(period: dict) -> tuple[datetime, datetime] | None:
    start_raw = period.get("start")
    end_raw = period.get("end")
    if not start_raw or not end_raw:
        return None
    start = datetime.combine(date.fromisoformat(str(start_raw)), time.min)
    end = datetime.combine(date.fromisoformat(str(end_raw)), time(23, 59, 59))
    return start, end


def slice_cons_data_for_period(
    cons_df: pd.DataFrame,
    period: dict,
) -> pd.DataFrame:
    bounds = nav_bounds_from_period(period)
    if bounds is None or cons_df.empty:
        return cons_df
    start, end = bounds
    mask = (cons_df.index >= start) & (cons_df.index <= end)
    return cons_df.loc[mask]


def reference_consumption_subheader(period: dict) -> str:
    if is_single_month_test_run(period):
        month = int(period["start_month"])
        year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
        return f"Referenz-Verbrauch (Testmonat {month:02d}/{year}, nicht optimiert)"
    return "Referenz-Jahresverbrauch (nicht optimiert)"


def _flex_kw_columns(cons_df: pd.DataFrame) -> list[str]:
    configured = [f"{c['id']}_kw" for c in config.get_flexible_consumers()]
    if configured:
        matched = [col for col in configured if col in cons_df.columns]
        if matched:
            return matched
    from data.cons_data_house_profile import expected_cons_data_consumer_ids

    expected = [f"{cid}_kw" for cid in expected_cons_data_consumer_ids()]
    if expected:
        return [col for col in expected if col in cons_df.columns]
    skip = {"total", "baseload", "pv"}
    return [
        col
        for col in cons_df.columns
        if col.endswith("_kw") and col[: -len("_kw")] not in skip
    ]


def cons_data_has_flex_energy(cons_df: pd.DataFrame) -> bool:
    """False wenn Verbraucher-Spalten fehlen oder überall 0 sind."""
    flex_cols = _flex_kw_columns(cons_df)
    if not flex_cols:
        return False
    return float(cons_df[flex_cols].sum().sum()) > 0.0


def reference_kwh_for_period(cons_df: pd.DataFrame, period: dict) -> float | None:
    sliced = slice_cons_data_for_period(cons_df, period)
    if sliced.empty:
        return None
    monthly = cons_data_monthly_kwh(sliced)
    return round(sum(monthly.values()), 1)


def build_annual_cost_rows(meta: dict, ref_kwh: float | None) -> list[dict]:
    summary = meta.get("summary", {})
    totals = summary.get("total_eur", {})
    labels = meta.get("labels", {})
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    ref_total = totals.get(ref_id)

    rows: list[dict] = []
    for scenario_id, total_eur in totals.items():
        label = labels.get(scenario_id, scenario_id)
        is_ref = scenario_id == ref_id
        kwh_cell = f"{ref_kwh:.0f}" if is_ref and ref_kwh is not None else _DASH
        delta_cell = _DASH
        if not is_ref and ref_total is not None:
            delta_cell = f"{total_eur - ref_total:+.2f} €"
        rows.append(
            {
                "Szenario": label,
                "Jahres-kWh": kwh_cell,
                "Jahres-€": f"{total_eur:.2f}",
                "Δ vs. Referenz": delta_cell,
            }
        )
    return rows
