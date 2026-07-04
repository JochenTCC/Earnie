"""Gemeinsame Darstellung von Simulationsergebnissen (Live + Historisch)."""
from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

from runtime_store import live_optimization_debug
from runtime_store.history_timeline import HistoryTimelineResult, format_gap_notice
from ui.chart_context import (
    LiveChartContext,
    align_rows_to_chart_slots,
    savings_view_for_chart,
)
from ui.charts import build_sun_markers, render_history_optimization_chart, render_optimization_chart

logger = logging.getLogger("app")


def _cost_totals_from_savings(savings: dict) -> tuple[float | None, float | None]:
    """Gesamtkosten BL Ziel und optimiert aus dem Savings-Dict."""
    if "optimized_cost_euro" not in savings:
        return None, None
    matched_key = (
        "matched_baseline_cost_euro"
        if "matched_baseline_cost_euro" in savings
        else "baseline_cost_euro"
    )
    if matched_key not in savings:
        return None, None
    return savings[matched_key], savings["optimized_cost_euro"]


def render_applied_targets(savings: dict) -> None:
    """Zeigt Baseline- und Optimierungsenergie je Verbraucher in einer Tabelle."""
    comparison = savings.get("energy_comparison") or []
    if not comparison:
        return

    with st.expander("⚡ Energievergleich Baseline vs. Optimierung (24h)"):
        st.caption(
            "BL Profil: historisches Flex-Profil. BL Ziel: gleiche Energie wie die Optimierung "
            "(Profil skaliert), ohne Lastverschiebung."
        )

        def _format_kwh_cell(kwh: float) -> str:
            return f"{kwh:.1f} kWh"

        def _format_optimization_cell(kwh: float, source: str) -> str:
            formatted = _format_kwh_cell(kwh)
            if source:
                return f"{formatted} ({source})"
            return formatted

        st.dataframe(
            pd.DataFrame([
                {
                    "Verbraucher": row["name"],
                    "BL Profil (kWh)": _format_kwh_cell(row["baseline_kwh"]),
                    "BL Ziel (kWh)": _format_kwh_cell(row.get("matched_baseline_kwh", 0.0)),
                    "Optimierung": _format_optimization_cell(
                        row["optimization_kwh"],
                        row.get("optimization_source", ""),
                    ),
                }
                for row in comparison
            ]),
            width="stretch",
            hide_index=True,
        )


def render_simulation_details(
    df: pd.DataFrame,
    title: str = "📋 Simulations-Details (Nächste 24 Stunden)",
) -> None:
    with st.expander(title):
        st.markdown(
            "Hier sind die exakten mathematischen Stundenslots aufgelistet, "
            "die als Grundlage für den Chart dienen:"
        )
        st.dataframe(df, width="stretch")


def render_optimization_results(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
    simulation_table_title: str | None = "📋 Simulations-Details (Nächste 24 Stunden)",
    chart_context: LiveChartContext | None = None,
    optimization_matrix: list | None = None,
) -> None:
    if matched_baseline_df is None and savings_info.get("matched_baseline_rows"):
        matched_baseline_df = pd.DataFrame(savings_info["matched_baseline_rows"])

    savings_view = savings_info
    display_df = optimized_df
    display_matched = matched_baseline_df
    sun_markers = None
    if chart_context is not None and optimization_matrix is not None:
        savings_view = savings_view_for_chart(
            savings_info,
            optimization_matrix,
            chart_context.chart_window,
        )
        display_df = pd.DataFrame(
            align_rows_to_chart_slots(
                optimized_df.to_dict("records"),
                chart_context.chart_window,
            )
        )
        if matched_baseline_df is not None:
            display_matched = pd.DataFrame(
                align_rows_to_chart_slots(
                    matched_baseline_df.to_dict("records"),
                    chart_context.chart_window,
                )
            )
        sun_markers = build_sun_markers(
            chart_context.chart_window,
            chart_context.zone_reference,
            chart_context.planning_window,
        )

    matched_cost, optimized_cost = _cost_totals_from_savings(savings_view)
    render_optimization_chart(
        display_df,
        baseline_df,
        display_matched,
        hourly_savings_euro=savings_view.get("hourly_savings_euro"),
        hourly_matched_baseline_cost_euro=savings_view.get(
            "hourly_matched_baseline_cost_euro"
        ),
        hourly_optimized_cost_euro=savings_view.get("hourly_optimized_cost_euro"),
        hourly_matched_baseline_consumption_kwh=savings_view.get(
            "hourly_matched_baseline_consumption_kwh"
        ),
        hourly_optimized_consumption_kwh=savings_view.get(
            "hourly_optimized_consumption_kwh"
        ),
        matched_baseline_cost_euro=matched_cost,
        optimized_cost_euro=optimized_cost,
        chart_window=chart_context.chart_window if chart_context else None,
        chart_now=chart_context.zone_reference if chart_context else None,
        chart_zones=chart_context.zones if chart_context else None,
        sun_markers=sun_markers,
    )
    render_applied_targets(savings_view)
    if simulation_table_title:
        table_title = simulation_table_title
        if chart_context is not None:
            table_title = (
                "📋 Simulations-Details (Sonnenaufgang→Sonnenaufgang)"
            )
        render_simulation_details(display_df, title=table_title)


def render_history_timeline_results(result: HistoryTimelineResult) -> None:
    """Zwei Charts aus rekonstruierter Produktiv-Historie (ohne Live-Simulation)."""
    df = pd.DataFrame(result.rows)
    st.caption(
        f"📜 **Produktiv-Historie** · {result.present_slot_count} von "
        f"{len(result.rows)} Slots mit Messwerten"
    )
    gap_notice = format_gap_notice(result)
    if gap_notice:
        st.warning(gap_notice)
    total_cost = (
        result.cumulative_costs_euro[-1]
        if result.cumulative_costs_euro
        else 0.0
    )
    render_history_optimization_chart(
        df,
        result.slot_costs_euro,
        result.slot_consumption_kwh,
        total_cost,
        projected_savings_cumulative_euro=result.projected_savings_cumulative_euro,
        latest_projected_savings_euro=result.latest_projected_savings_euro,
    )


def persist_simulation_debug(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    *,
    kind: str,
    initial_soc: float,
    main_state: dict | None = None,
    quarter_hour_slot: str | None = None,
    sync_reason: str | None = None,
    optimized_df_raw: pd.DataFrame | None = None,
    target_date: str | None = None,
    historical_meta: dict | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
) -> None:
    """Schreibt Simulationsergebnis als JSON in runtime/ (Debug / Nachrechnen)."""
    if matched_baseline_df is None and savings_info.get("matched_baseline_rows"):
        matched_baseline_df = pd.DataFrame(savings_info["matched_baseline_rows"])
    try:
        payload = live_optimization_debug.build_debug_payload(
            savings_info,
            optimized_df.to_dict("records"),
            baseline_df.to_dict("records"),
            kind=kind,
            initial_soc=initial_soc,
            main_state=main_state,
            quarter_hour_slot=quarter_hour_slot,
            sync_reason=sync_reason,
            optimized_rows_raw=(
                optimized_df_raw.to_dict("records") if optimized_df_raw is not None else None
            ),
            target_date=target_date,
            historical_meta=historical_meta,
            matched_baseline_rows=(
                matched_baseline_df.to_dict("records")
                if matched_baseline_df is not None
                else None
            ),
        )
        live_optimization_debug.save_debug_snapshot(payload, kind=kind)
    except (OSError, TypeError) as exc:
        logger.warning("Debug-Snapshot konnte nicht gespeichert werden: %s", exc)
