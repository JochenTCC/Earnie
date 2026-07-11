"""Abweichungsliste für Backtesting-Ergebnisse (1.25.d / Chart1/2 1.25.f)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import config

from simulation.backtesting_log import (
    dedupe_critical_cases_by_window,
    extract_critical_cases,
    summarize_critical_cases,
)
from simulation.engine import HISTORICAL_REFERENCE_ID
from simulation.horizon_mode import FIXED_24H
from ui.backtesting_display_bundle import (
    VIEW_MODE_24H,
    VIEW_MODE_SUNRISE,
    format_backtesting_window_range,
    load_backtesting_display_bundle,
    log_supports_sunrise_chart_view,
)
from ui.simulation_results import (
    render_optimization_chart1,
    render_optimization_chart2,
)

_DASH = "—"

KIND_LABELS: dict[str, str] = {
    "consumption_tolerance": "Verbrauchstoleranz",
    "strict_slow": "CBC strict (langsam)",
    "strict_fallback": "CBC Fallback",
    "milp_no_optimal": "MILP ohne Optimum",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def _format_window_anchor(anchor: str | None) -> str:
    if not anchor:
        return _DASH
    try:
        ts = datetime.fromisoformat(str(anchor).replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        return ts.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(anchor)


def _format_deviation_window(case: dict, meta: dict) -> str:
    anchor = case.get("window_anchor")
    if not anchor:
        return _DASH
    if log_supports_sunrise_chart_view(meta):
        return _format_window_anchor(str(anchor))
    return format_backtesting_window_range(
        str(anchor),
        config.get_planning_timezone(),
    )


def deviation_cases_for_display(meta: dict) -> list[dict]:
    """Kritische Fälle ohne Referenz-Szenario, dedupliziert pro Fenster."""
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    cases = extract_critical_cases(meta)
    filtered = [case for case in cases if case.get("scenario_id") != ref_id]
    return dedupe_critical_cases_by_window(filtered)


def format_deviation_delta_kwh(case: dict) -> str:
    if case.get("kind") != "consumption_tolerance":
        return _DASH
    diff = case.get("diff_kwh")
    if diff is None:
        return _DASH
    return f"{float(diff):+.2f}"


def build_deviation_table_rows(
    cases: list[dict],
    labels_map: dict[str, str],
    meta: dict,
) -> list[dict]:
    rows: list[dict] = []
    for case in cases:
        scenario_id = str(case.get("scenario_id", "?"))
        rows.append(
            {
                "Fenster": _format_deviation_window(case, meta),
                "Szenario": labels_map.get(scenario_id, scenario_id),
                "Art": kind_label(str(case.get("kind", "?"))),
                "Δ kWh (Soll/Ist)": format_deviation_delta_kwh(case),
            }
        )
    return rows


def case_to_plausibility_failure(case: dict) -> dict:
    return {
        "window_end": case.get("window_anchor"),
        "historical_kwh": case.get("historical_kwh"),
        "optimized_kwh": case.get("optimized_kwh"),
        "diff_kwh": case.get("diff_kwh"),
    }


def _scenario_label(case: dict, labels_map: dict[str, str]) -> str:
    scenario_id = str(case.get("scenario_id", "?"))
    return labels_map.get(scenario_id, scenario_id)


def _render_consumption_caption(case: dict) -> None:
    if case.get("kind") != "consumption_tolerance":
        return
    hist = case.get("historical_kwh")
    opt = case.get("optimized_kwh")
    diff = case.get("diff_kwh")
    if hist is not None and opt is not None and diff is not None:
        st.caption(
            f"Soll/Ist-Summen (24h): historisch {float(hist):.1f} kWh · "
            f"optimiert {float(opt):.1f} kWh · Δ {float(diff):+.2f} kWh"
        )


def _format_consumer_targets(targets: dict | None) -> str | None:
    if not targets:
        return None
    parts = [f"{key}={float(value):.3f} kWh" for key, value in sorted(targets.items())]
    return ", ".join(parts)


def _render_cbc_facts_caption(case: dict) -> None:
    facts: list[str] = []
    slot = case.get("slot_datetime")
    if slot:
        facts.append(f"Slot: {_format_window_anchor(str(slot))}")
    hour_idx = case.get("simulation_hour_index")
    if hour_idx is not None:
        facts.append(f"Simulationsstunde: {hour_idx}")
    elapsed = case.get("strict_elapsed_sec")
    if elapsed is not None:
        facts.append(f"Strict-Laufzeit: {float(elapsed):.2f} s")
    limit = case.get("strict_limit_sec")
    if limit is not None:
        facts.append(f"Strict-Limit: {float(limit):.2f} s")
    gap = case.get("gap_rel")
    if gap is not None:
        facts.append(f"Gap: {float(gap):.4f}")
    status = case.get("strict_status") or case.get("final_status")
    if status:
        facts.append(f"Status: {status}")
    targets = _format_consumer_targets(case.get("consumer_targets_kwh"))
    if targets:
        facts.append(f"Verbraucherziele: {targets}")
    if facts:
        st.caption(" · ".join(facts))


def _resolve_chart_view(
    meta: dict,
    *,
    segment_toggle: str,
) -> tuple[str, int]:
    """Chart-Ansicht folgt dem Planungshorizont des Backtesting-Logs."""
    if not log_supports_sunrise_chart_view(meta):
        return VIEW_MODE_24H, 0
    segment_index = 0 if segment_toggle == "SA₀→SA₁" else 1
    return VIEW_MODE_SUNRISE, segment_index


def _render_deviation_charts(
    case: dict,
    meta: dict,
    log_dir: str,
) -> None:
    segment_toggle = "SA₀→SA₁"
    if log_supports_sunrise_chart_view(meta):
        segment_toggle = st.radio(
            "SA-Segment",
            options=["SA₀→SA₁", "SA₁→SA₂"],
            horizontal=True,
            key="backtesting_deviation_sa_segment",
        )

    view_mode, segment_index = _resolve_chart_view(
        meta,
        segment_toggle=segment_toggle,
    )

    log_horizon = meta.get("period", {}).get("horizon_mode", FIXED_24H)
    window_anchor = str(case.get("window_anchor", ""))
    scenario_id = str(case.get("scenario_id", ""))
    try:
        bundle = load_backtesting_display_bundle(
            log_dir,
            window_anchor,
            scenario_id,
            view_mode=view_mode,
            segment_index=segment_index,
            log_horizon_mode=log_horizon,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    if bundle is None:
        st.info(
            "Kein Fenster-Snapshot für diesen Horizont — nur bei Abweichungen gespeichert. "
            "Backtesting mit kritischem Fenster erneut ausführen oder Horizont wechseln."
        )
        return

    chart_suffix = f"{view_mode}_{segment_index}"
    render_optimization_chart1(
        bundle,
        chart_key=f"backtesting_power_soc_{chart_suffix}",
    )
    render_optimization_chart2(
        bundle,
        chart_key=f"backtesting_price_savings_{chart_suffix}",
    )


def render_deviation_detail(
    case: dict,
    labels_map: dict[str, str],
    *,
    meta: dict,
    log_dir: str,
) -> None:
    window = _format_deviation_window(case, meta)
    scenario = _scenario_label(case, labels_map)
    art = kind_label(str(case.get("kind", "?")))
    st.markdown(f"**Fenster:** {window} · **Szenario:** {scenario} · **Art:** {art}")
    _render_consumption_caption(case)
    if case.get("kind") != "consumption_tolerance":
        _render_cbc_facts_caption(case)
    _render_deviation_charts(case, meta, log_dir)


def _selected_deviation_index(table_state, row_count: int) -> int:
    if row_count <= 0:
        return 0
    selection = getattr(table_state, "selection", None)
    rows = getattr(selection, "rows", None) if selection is not None else None
    if rows:
        index = int(rows[0])
        if 0 <= index < row_count:
            return index
    return 0


def render_deviation_list(
    meta: dict,
    labels_map: dict[str, str],
    *,
    log_dir: str,
) -> None:
    st.subheader("Abweichungsliste")

    cases = deviation_cases_for_display(meta)
    if not cases:
        st.info("Keine auffälligen Abweichungen im Backtesting-Lauf.")
        return

    summary = summarize_critical_cases(cases)
    st.caption(
        f"{summary['total']} Einträge in {summary['distinct_windows']} Fenstern"
    )
    rows = build_deviation_table_rows(cases, labels_map, meta)

    table_state = st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="backtesting_deviation_table",
    )
    selected_index = _selected_deviation_index(table_state, len(cases))
    render_deviation_detail(
        cases[selected_index],
        labels_map,
        meta=meta,
        log_dir=log_dir,
    )
