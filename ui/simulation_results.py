"""Gemeinsame Darstellung von Simulationsergebnissen (Live + Historisch)."""
from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

from runtime_store import live_optimization_debug
from runtime_store.history_timeline import (
    HistoryTimelineResult,
    SLOT_MISSING,
    SLOT_PRESENT,
    format_gap_notice,
)
from ui.chart_context import (
    LiveChartContext,
    SLOT_MILP,
    align_rows_to_display_slots,
    build_chart_display_context,
    build_display_savings_series,
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


_TABLE_MISSING_ROW_COLOR = "background-color: #ffe0b2;"
_SLOT_QUALITY_LABELS = {
    SLOT_PRESENT: "Produktiv-Log",
    SLOT_MISSING: "fehlend",
    SLOT_MILP: "MILP",
}


def _slot_quality_label(quality: str) -> str:
    return _SLOT_QUALITY_LABELS.get(quality, quality)


def _quality_at_row(row_index, frame_index: pd.Index, qualities: tuple[str, ...]) -> str:
    position = int(frame_index.get_loc(row_index))
    return qualities[position]


def _style_simulation_table(
    df: pd.DataFrame,
    slot_qualities: tuple[str, ...],
) -> pd.io.formats.style.Styler:
    """
    Zeilen-Hintergrund für fehlende Log-Slots (orange).

    st.dataframe unterstützt Styler.apply, aber nicht zuverlässig mit hide() —
    Qualitäten liegen daher außerhalb des DataFrames.
    """

    def _highlight_row(row: pd.Series):
        quality = _quality_at_row(row.name, df.index, slot_qualities)
        if quality != SLOT_MISSING:
            return [None] * len(row)
        return [_TABLE_MISSING_ROW_COLOR] * len(row)

    return df.style.apply(_highlight_row, axis=1)


def _render_simulation_table(
    df: pd.DataFrame,
    slot_qualities: tuple[str, ...] | None,
) -> None:
    display_df = df.copy()
    if slot_qualities is not None:
        if len(slot_qualities) != len(display_df):
            raise ValueError(
                f"slot_qualities ({len(slot_qualities)}) passt nicht zur Tabelle "
                f"({len(display_df)} Zeilen)."
            )
        display_df["Datenquelle"] = [_slot_quality_label(q) for q in slot_qualities]
    if "slot_datetime" in display_df.columns:
        display_df = display_df.drop(columns=["slot_datetime"])

    has_gap_styles = slot_qualities is not None and any(
        quality == SLOT_MISSING for quality in slot_qualities
    )
    if has_gap_styles:
        # st.table rendert Pandas-Styler (Zeilenfarben) zuverlässiger als st.dataframe.
        st.table(_style_simulation_table(display_df, slot_qualities))
    else:
        st.dataframe(display_df, width="stretch", hide_index=True)


def render_simulation_details(
    df: pd.DataFrame,
    title: str = "📋 Simulations-Details (Nächste 24 Stunden)",
    *,
    slot_qualities: tuple[str, ...] | None = None,
    gap_notice: str | None = None,
) -> None:
    with st.expander(title):
        if gap_notice:
            st.warning(gap_notice)
        st.markdown(
            "Slots wie im Chart: **Produktiv-Log** (15 min, grauer Bereich) und "
            "**MILP** (laufende Stunde ab x:15 in 15-min-Soll-Slots, sonst 1 h ab voller Stunde). "
            "**Orange** = kein Log-Eintrag (Werte leer, kein Hold-Forward)."
        )
        _render_simulation_table(df, slot_qualities)


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
    table_df = display_df
    table_qualities: tuple[str, ...] | None = None
    table_gap_notice: str | None = None
    chart_qualities: tuple[str, ...] | None = None
    sun_markers = None
    if chart_context is not None and optimization_matrix is not None:
        savings_view = savings_view_for_chart(
            savings_info,
            optimization_matrix,
            chart_context.chart_window,
        )
        display_ctx = build_chart_display_context(
            chart_context,
            optimized_df.to_dict("records"),
        )
        savings_view = build_display_savings_series(
            display_ctx,
            savings_view,
            optimization_matrix,
            chart_context.chart_window,
        )
        table_df = pd.DataFrame(display_ctx.rows)
        table_qualities = display_ctx.slot_qualities
        chart_qualities = display_ctx.slot_qualities
        table_gap_notice = display_ctx.gap_notice
        display_df = pd.DataFrame(display_ctx.rows)
        if matched_baseline_df is not None:
            display_matched = pd.DataFrame(
                align_rows_to_display_slots(
                    matched_baseline_df.to_dict("records"),
                    display_ctx.slot_datetimes,
                )
            )
        sun_markers = build_sun_markers(
            chart_context.chart_window,
            chart_context.now,
            chart_context.planning_window,
            slot_datetimes=display_ctx.slot_datetimes,
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
        slot_qualities=chart_qualities,
    )
    render_applied_targets(savings_view)
    if simulation_table_title:
        table_title = simulation_table_title
        if chart_context is not None:
            table_title = (
                "📋 Simulations-Details (Sunset-2-Sunset-Fenster)"
            )
        render_simulation_details(
            table_df,
            title=table_title,
            slot_qualities=table_qualities,
            gap_notice=table_gap_notice,
        )


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
    render_simulation_details(
        df,
        title="📋 Simulations-Details (Produktiv-Historie, 15 min)",
        slot_qualities=result.slot_qualities,
        gap_notice=format_gap_notice(result),
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
