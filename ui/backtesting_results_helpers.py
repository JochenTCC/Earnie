"""Hilfsfunktionen für Backtesting-Ergebnisanzeige (Perioden, Kostentabelle)."""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

import config
from scripts.run_backtesting import BACKTESTING_YEAR
from simulation.engine import HISTORICAL_REFERENCE_ID, is_scenario_reference_id
from ui.consumption_validation_charts import cons_data_monthly_kwh

_DASH = "—"
_TIMING_SHIFT_NOTE = "Zeitliche Lastverschiebung (Energie ≈ Spec)"


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
    from settings.flexible_consumers import runtime_consumer_id
    from ui.chart_consumer_stack import _chart_flex_consumers

    configured = [f"{runtime_consumer_id(c)}_kw" for c in _chart_flex_consumers(optimizer_only=False)]
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


def scenario_consumption_subheader(period: dict) -> str:
    if is_single_month_test_run(period):
        month = int(period["start_month"])
        year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
        return f"Verbrauchsvergleich (Debug, Testmonat {month:02d}/{year})"
    return "Verbrauchsvergleich (Debug)"


def _format_kwh(value: float | None) -> str:
    if value is None:
        return _DASH
    return f"{value:.1f}"


def _format_delta_kwh(value: float | None) -> str:
    if value is None:
        return _DASH
    return f"{value:+.1f}"


def _format_plausibility_cell(block: dict | None) -> str:
    if not block:
        return _DASH
    ok = block.get("ok_count")
    total = block.get("total_windows")
    if ok is None or total is None:
        return _DASH
    return f"{ok}/{total} OK"


def _format_flex_delta_kwh(totals: dict) -> str:
    historical = totals.get("historical_flex_kwh")
    optimized = totals.get("optimized_flex_kwh")
    if historical is None or optimized is None:
        return _DASH
    return _format_delta_kwh(round(optimized - historical, 1))


def _timing_shift_note(
    scenario_id: str,
    totals: dict,
    labels: dict[str, str],
    *,
    hourly_df,
    scenarios: dict | None,
    timestamps: list[str] | None,
) -> str:
    delta = totals.get("delta_kwh")
    if delta is None or hourly_df is None or not scenarios or not timestamps:
        return _DASH
    from ui.backtesting_scenario_consumption import (
        build_baseline_optimized_overlay,
        detect_period_timing_shift,
    )

    overlay = build_baseline_optimized_overlay(
        scenarios,
        labels,
        scenario_id,
        timestamps,
        hourly_df,
    )
    if overlay is None:
        return _DASH
    if detect_period_timing_shift(overlay.baseline_kw, overlay.optimized_kw):
        return _TIMING_SHIFT_NOTE
    return _DASH


def build_scenario_consumption_rows(
    meta: dict,
    ref_kwh: float | None,
    *,
    hourly_df=None,
    scenarios: dict | None = None,
    timestamps: list[str] | None = None,
) -> list[dict]:
    """Vergleich Baseline-Spec vs. optimierter kWh je Szenario (Debug-Tabelle)."""
    labels = meta.get("labels", {})
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    plausibility = meta.get("plausibility", {})
    scenario_ids = list(meta.get("scenario_ids", []))
    if ref_id not in scenario_ids:
        scenario_ids.insert(0, ref_id)

    rows: list[dict] = []
    for scenario_id in scenario_ids:
        label = labels.get(scenario_id, scenario_id)
        is_ref = scenario_id == ref_id
        block = plausibility.get(scenario_id)
        totals = (block or {}).get("consumption_totals") or {}

        if is_ref:
            baseline = ref_kwh
            optimized = ref_kwh
            delta = 0.0 if ref_kwh is not None else None
            flex_delta = _DASH
            plaus_cell = _DASH
            note = _DASH
        else:
            baseline = totals.get("historical_kwh")
            optimized = totals.get("optimized_kwh")
            delta = totals.get("delta_kwh")
            flex_delta = _format_flex_delta_kwh(totals)
            plaus_cell = _format_plausibility_cell(block)
            note = _timing_shift_note(
                scenario_id,
                totals,
                labels,
                hourly_df=hourly_df,
                scenarios=scenarios,
                timestamps=timestamps,
            )

        rows.append(
            {
                "Szenario": label,
                "Baseline Spec (kWh)": _format_kwh(baseline),
                "Optimiert (kWh)": _format_kwh(optimized),
                "Δ kWh (Opt−Baseline)": _format_delta_kwh(delta),
                "Δ Flex (kWh)": flex_delta,
                "Hinweis": note,
                "Plausibilität": plaus_cell,
            }
        )
    return rows


def _reference_id_for_scenario(meta: dict, scenario_id: str) -> str:
    mapping = meta.get("reference_by_scenario") or {}
    return str(mapping.get(scenario_id) or meta.get("reference_id", HISTORICAL_REFERENCE_ID))


def _annual_cost_row_order(meta: dict, totals: dict[str, float]) -> list[str]:
    """Global reference first, then per-scenario references, then optimized scenarios."""
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    scenario_ids = list(meta.get("scenario_ids", []))
    ordered_ids = list(dict.fromkeys(scenario_ids + [sid for sid in totals if sid not in scenario_ids]))

    global_refs: list[str] = []
    scenario_refs: list[str] = []
    optimized: list[str] = []
    for scenario_id in ordered_ids:
        if scenario_id not in totals:
            continue
        if scenario_id == ref_id:
            global_refs.append(scenario_id)
        elif is_scenario_reference_id(scenario_id):
            scenario_refs.append(scenario_id)
        else:
            optimized.append(scenario_id)
    return global_refs + scenario_refs + optimized


def build_annual_cost_rows(meta: dict, ref_kwh: float | None) -> list[dict]:
    summary = meta.get("summary", {})
    totals = summary.get("total_eur", {})
    labels = meta.get("labels", {})
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)

    rows: list[dict] = []
    for scenario_id in _annual_cost_row_order(meta, totals):
        total_eur = totals[scenario_id]
        label = labels.get(scenario_id, scenario_id)
        is_reference = scenario_id == ref_id or is_scenario_reference_id(scenario_id)
        if is_reference:
            kwh_cell = _format_kwh(ref_kwh) if scenario_id == ref_id else _DASH
            rows.append(
                {
                    "Szenario": label,
                    "Jahres-kWh": kwh_cell,
                    "Jahres-€": f"{total_eur:.2f}",
                    "Δ vs. Referenz": _DASH,
                }
            )
            continue

        scenario_ref_id = _reference_id_for_scenario(meta, scenario_id)
        ref_total = totals.get(scenario_ref_id)
        if ref_total is None and scenario_ref_id != ref_id:
            ref_total = totals.get(ref_id)
        delta_cell = _DASH
        if ref_total is not None:
            delta_cell = f"{total_eur - ref_total:+.2f} €"
        rows.append(
            {
                "Szenario": label,
                "Jahres-kWh": _DASH,
                "Jahres-€": f"{total_eur:.2f}",
                "Δ vs. Referenz": delta_cell,
            }
        )
    return rows
