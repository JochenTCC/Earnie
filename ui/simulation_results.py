"""Gemeinsame Darstellung von Simulationsergebnissen (Live + Historisch)."""
from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

from runtime_store import live_optimization_debug
from runtime_store.history_timeline import HistoryTimelineResult, format_gap_notice
from ui.charts import render_history_optimization_chart, render_optimization_chart

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
) -> None:
    if matched_baseline_df is None and savings_info.get("matched_baseline_rows"):
        matched_baseline_df = pd.DataFrame(savings_info["matched_baseline_rows"])
    matched_cost, optimized_cost = _cost_totals_from_savings(savings_info)
    render_optimization_chart(
        optimized_df,
        baseline_df,
        matched_baseline_df,
        hourly_savings_euro=savings_info.get("hourly_savings_euro"),
        hourly_matched_baseline_cost_euro=savings_info.get(
            "hourly_matched_baseline_cost_euro"
        ),
        hourly_optimized_cost_euro=savings_info.get("hourly_optimized_cost_euro"),
        hourly_matched_baseline_consumption_kwh=savings_info.get(
            "hourly_matched_baseline_consumption_kwh"
        ),
        hourly_optimized_consumption_kwh=savings_info.get(
            "hourly_optimized_consumption_kwh"
        ),
        matched_baseline_cost_euro=matched_cost,
        optimized_cost_euro=optimized_cost,
    )
    render_applied_targets(savings_info)
    if simulation_table_title:
        render_simulation_details(optimized_df, title=simulation_table_title)


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
    except OSError as exc:
        logger.warning("Debug-Snapshot konnte nicht gespeichert werden: %s", exc)
