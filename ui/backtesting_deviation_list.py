"""Abweichungsliste für Backtesting-Ergebnisse (Kalender-Navigator + Chart1/2)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import config

from simulation.backtesting_log import extract_critical_cases, summarize_critical_cases
from simulation.engine import HISTORICAL_REFERENCE_ID, HistoricalDataCache, list_simulation_anchors
from ui.backtesting_deviation_calendar import (
    build_deviation_calendar_index,
    cases_for_date_and_scenario,
    default_calendar_date,
    deviation_marker_for_case,
    render_deviation_calendar,
)
from ui.backtesting_diag_single_window import render_diag_single_window_panel
from ui.backtesting_display_bundle import (
    VIEW_MODE_24H,
    VIEW_MODE_SUNRISE,
    format_backtesting_window_range,
    log_supports_sunrise_chart_view,
    resolve_backtesting_display_bundle,
)
from ui.backtesting_results_helpers import nav_bounds_from_period
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
    from simulation.backtesting_log import dedupe_critical_cases_by_window

    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    cases = extract_critical_cases(meta)
    filtered = [case for case in cases if case.get("scenario_id") != ref_id]
    return dedupe_critical_cases_by_window(filtered)


def format_deviation_delta_kwh(case: dict) -> str:
    if case.get("kind") == "consumption_tolerance":
        diff = case.get("diff_kwh")
        if diff is None:
            return _DASH
        return f"{float(diff):+.2f}"
    window_diff = case.get("window_consumption_diff_kwh")
    if window_diff is not None:
        return f"{float(window_diff):+.2f}"
    return _DASH


def case_to_plausibility_failure(case: dict) -> dict:
    return {
        "window_end": case.get("window_anchor"),
        "historical_kwh": case.get("historical_kwh"),
        "optimized_kwh": case.get("optimized_kwh"),
        "diff_kwh": case.get("diff_kwh"),
    }


def _scenario_label(scenario_id: str, labels_map: dict[str, str]) -> str:
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
    if case.get("window_consumption_ok") is True:
        facts.append("24h-Gesamtverbrauch: innerhalb Toleranz")
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


def _render_sa_segment_toggle(meta: dict) -> str:
    if not log_supports_sunrise_chart_view(meta):
        return "SA₀→SA₁"
    return st.radio(
        "SA-Segment",
        options=["SA₀→SA₁", "SA₁→SA₂"],
        horizontal=True,
        key="backtesting_deviation_sa_segment",
    )


def _render_deviation_charts(
    window_anchor: str,
    scenario_id: str,
    meta: dict,
    log_dir: str,
    hourly_df: pd.DataFrame,
    *,
    segment_toggle: str,
) -> None:
    view_mode, segment_index = _resolve_chart_view(
        meta,
        segment_toggle=segment_toggle,
    )

    try:
        bundle = resolve_backtesting_display_bundle(
            log_dir,
            window_anchor,
            scenario_id,
            meta,
            hourly_df,
            view_mode=view_mode,
            segment_index=segment_index,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    if bundle is None:
        st.info(
            "Chart-Daten für dieses Fenster konnten nicht geladen werden."
        )
        return

    chart_suffix = f"{view_mode}_{segment_index}_{scenario_id}"
    render_optimization_chart1(
        bundle,
        chart_key=f"backtesting_power_soc_{chart_suffix}",
    )
    render_optimization_chart2(
        bundle,
        chart_key=f"backtesting_price_savings_{chart_suffix}",
    )


def _optimized_scenario_ids(meta: dict) -> list[str]:
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    return [
        str(scenario_id)
        for scenario_id in meta.get("scenario_ids", [])
        if scenario_id != ref_id
    ]


def _run_anchors_for_meta(meta: dict) -> list[datetime]:
    bounds = nav_bounds_from_period(meta.get("period") or {})
    if bounds is None:
        return []
    start, end = bounds
    cache = HistoricalDataCache()
    return list_simulation_anchors(pd.Timestamp(start), pd.Timestamp(end), cache)



def _default_active_scenario(
    scenario_options: list[str],
    cases_by_scenario: dict[str, dict],
    *,
    live_scenario_id: str | None = None,
) -> str:
    for scenario_id in scenario_options:
        if scenario_id in cases_by_scenario:
            return scenario_id
    if live_scenario_id and live_scenario_id in scenario_options:
        return live_scenario_id
    return scenario_options[0]


def _scenario_option_label(
    scenario_id: str,
    labels_map: dict[str, str],
    case: dict | None,
) -> str:
    marker = deviation_marker_for_case(case)
    label = _scenario_label(scenario_id, labels_map)
    if marker:
        return f"{marker} {label}"
    return label


def _select_scenario_from_radio(
    selected_date: date,
    scenario_options: list[str],
    cases_by_scenario: dict[str, dict],
    labels_map: dict[str, str],
) -> str | None:
    """Einzel-Auswahl per Radio-Liste; Abweichungen am Label markiert."""
    if not scenario_options:
        return None
    default = _default_active_scenario(
        scenario_options,
        cases_by_scenario,
        live_scenario_id=config.get_live_scenario_id(),
    )
    default_index = scenario_options.index(default)
    st.caption("Markierung = Abweichung an diesem Tag")
    return st.radio(
        "Szenario",
        options=scenario_options,
        index=default_index,
        format_func=lambda sid: _scenario_option_label(
            sid,
            labels_map,
            cases_by_scenario.get(sid),
        ),
        horizontal=True,
        key=f"backtesting_cal_scenario_{selected_date.isoformat()}",
    )


def render_deviation_detail(
    case: dict | None,
    labels_map: dict[str, str],
    *,
    meta: dict,
    log_dir: str,
    hourly_df: pd.DataFrame,
    window_anchor: str,
    scenario_id: str,
    segment_toggle: str,
) -> None:
    window = _format_deviation_window({"window_anchor": window_anchor}, meta)
    scenario = _scenario_label(scenario_id, labels_map)
    if case is None:
        st.markdown(
            f"**Fenster:** {window} · **Szenario:** {scenario} · **Keine Abweichung**"
        )
    else:
        art = kind_label(str(case.get("kind", "?")))
        delta = format_deviation_delta_kwh(case)
        st.markdown(
            f"**Fenster:** {window} · **Szenario:** {scenario} · **Art:** {art} · "
            f"**Δ kWh (Soll/Ist):** {delta}"
        )
        _render_consumption_caption(case)
        if case.get("kind") != "consumption_tolerance":
            _render_cbc_facts_caption(case)
    render_diag_single_window_panel(
        window_anchor,
        scenario_id,
        meta,
        hourly_df,
    )
    _render_deviation_charts(
        window_anchor,
        scenario_id,
        meta,
        log_dir,
        hourly_df,
        segment_toggle=segment_toggle,
    )


_DETAIL_MODE_OVERVIEW = "overview"
_DETAIL_MODE_CHARTS = "charts"


def _render_detail_mode_radio() -> str:
    return st.radio(
        "Detailansicht",
        options=[_DETAIL_MODE_OVERVIEW, _DETAIL_MODE_CHARTS],
        format_func=lambda mode: (
            "Nur Übersicht (Kalender + Metadaten)"
            if mode == _DETAIL_MODE_OVERVIEW
            else "Charts & Diagnose laden"
        ),
        horizontal=True,
        key="backtesting_deviation_detail_mode",
    )


def render_deviation_list(
    meta: dict,
    labels_map: dict[str, str],
    *,
    log_dir: str,
    hourly_df: pd.DataFrame,
) -> None:
    st.subheader("Detaillierte Simulationsansicht")

    run_anchors = _run_anchors_for_meta(meta)
    if not run_anchors:
        st.info("Keine Simulationsfenster im Backtesting-Zeitraum.")
        return

    cases = deviation_cases_for_display(meta)
    index = build_deviation_calendar_index(meta, cases, run_anchors=run_anchors)

    if cases:
        summary = summarize_critical_cases(cases)
        st.caption(
            f"{summary['total']} Abweichungen in {summary['distinct_windows']} Fenstern"
        )
    else:
        st.caption("Keine auffälligen Abweichungen — alle in-run Tage sind dennoch wählbar.")

    selected_date = render_deviation_calendar(index, meta)
    if selected_date is None:
        selected_date = default_calendar_date(index)
    if selected_date is None:
        return

    fallback_ids = _optimized_scenario_ids(meta)
    if not fallback_ids:
        st.info("Kein optimiertes Szenario für den gewählten Tag.")
        return

    cell = index[selected_date]
    cases_by_scenario = cell.cases_by_scenario
    with_deviation = [sid for sid in fallback_ids if sid in cases_by_scenario]
    without_deviation = [sid for sid in fallback_ids if sid not in cases_by_scenario]
    scenario_options = with_deviation + without_deviation

    scenario_id = _select_scenario_from_radio(
        selected_date,
        scenario_options,
        cases_by_scenario,
        labels_map,
    )
    if not scenario_id:
        return

    window_anchor = cell.anchor_iso or ""
    detail_mode = _render_detail_mode_radio()
    case = cases_for_date_and_scenario(index, selected_date, scenario_id)
    if detail_mode == _DETAIL_MODE_OVERVIEW:
        window = _format_deviation_window({"window_anchor": window_anchor}, meta)
        scenario = _scenario_label(scenario_id, labels_map)
        if case is None:
            st.markdown(
                f"**Fenster:** {window} · **Szenario:** {scenario} · **Keine Abweichung**"
            )
        else:
            art = kind_label(str(case.get("kind", "?")))
            delta = format_deviation_delta_kwh(case)
            st.markdown(
                f"**Fenster:** {window} · **Szenario:** {scenario} · **Art:** {art} · "
                f"**Δ kWh (Soll/Ist):** {delta}"
            )
            _render_consumption_caption(case)
            if case.get("kind") != "consumption_tolerance":
                _render_cbc_facts_caption(case)
        st.info(
            "Charts und Fenster-Diagnose werden erst nach Auswahl "
            "„Charts & Diagnose laden“ berechnet."
        )
        return

    segment_toggle = _render_sa_segment_toggle(meta)
    render_deviation_detail(
        case,
        labels_map,
        meta=meta,
        log_dir=log_dir,
        hourly_df=hourly_df,
        window_anchor=window_anchor,
        scenario_id=scenario_id,
        segment_toggle=segment_toggle,
    )
