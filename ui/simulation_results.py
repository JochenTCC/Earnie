"""Gemeinsame Darstellung von Simulationsergebnissen (Live + Historisch)."""
from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

import config
from data.planning_window import ui_chart_zones
from optimizer.targets import consumer_column_name
from runtime_store import live_optimization_debug
from runtime_store import optimization_history
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
from ui.charts import (
    _mask_missing_log_slots,
    build_sun_markers,
    render_history_optimization_chart,
    render_optimization_chart,
)
from ui.simulation_table_view import render_frozen_simulation_table

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


def _simulation_table_column_order(columns: list[str]) -> list[str]:
    """Uhrzeit und Flex-kW-Spalten nach vorne — weniger Verwechslung in der UI."""
    front = [name for name in ("Uhrzeit", "Datenquelle") if name in columns]
    flex_kw: list[str] = []
    immediate: list[str] = []
    pv_follow: list[str] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        power_col = consumer_column_name(consumer)
        if power_col in columns:
            flex_kw.append(power_col)
        imm_col = f"{consumer['name']} sofort_laden"
        if imm_col in columns:
            immediate.append(imm_col)
        pv_col = f"{consumer['name']} pv_follow"
        if pv_col in columns:
            pv_follow.append(pv_col)
    used = set(front + flex_kw + immediate + pv_follow)
    rest = [col for col in columns if col not in used]
    return front + flex_kw + immediate + pv_follow + rest


def _format_simulation_table_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Gleiche Dezimaldarstellung wie im Chart-Hover (2 Nachkommastellen)."""
    out = df.copy()
    numeric_suffixes = (" (kW)", " (Cent/kWh)", " (%)")
    for col in out.columns:
        if not any(token in col for token in numeric_suffixes):
            continue
        out[col] = out[col].apply(
            lambda value: None
            if value is None or (isinstance(value, float) and pd.isna(value))
            else round(float(value), 2)
        )
    return out


def format_display_data_basis_path(
    log_source: optimization_history.ProductionLogSourceInfo,
) -> str:
    """Kurzlabel für eingeklappte Datenbasis (nur Produktiv-Log-Pfad)."""
    return log_source.history_file


def format_display_data_basis_caption(
    log_source: optimization_history.ProductionLogSourceInfo,
    *,
    merge_active: bool,
    history_slot_count: int | None = None,
) -> str:
    """Markdown für ausgeklappte Datenbasis: Runtime, Merge-Pfad, Flex-Soll."""
    if log_source.env_runtime_dir:
        runtime_note = (
            f"`ENERGY_OPTIMIZER_RUNTIME_DIR` = `{log_source.env_runtime_dir}` "
            f"(aufgelöst: `{log_source.runtime_dir}`)"
        )
    else:
        runtime_note = (
            "Keine `ENERGY_OPTIMIZER_RUNTIME_DIR` gesetzt — "
            f"Standard `{log_source.runtime_dir}`"
        )
    if log_source.history_exists:
        modified = ""
        if log_source.history_modified_at is not None:
            modified = (
                f", zuletzt geändert "
                f"{log_source.history_modified_at:%d.%m.%Y %H:%M:%S}"
            )
        size = log_source.history_size_bytes or 0
        file_note = (
            f"**Produktiv-Log:** `{log_source.history_file}` "
            f"({size} Bytes{modified})"
        )
    else:
        file_note = (
            f"**Produktiv-Log:** `{log_source.history_file}` — "
            "**Datei nicht gefunden** (graue Slots ohne Log-Einträge)"
        )
    legacy_note = ""
    if log_source.legacy_csv_exists:
        legacy_note = (
            f" Zusätzlich Legacy-CSV: `{log_source.legacy_csv_file}` "
            "(nur Lückenfüller für Zeitpunkte ohne JSONL-Eintrag)."
        )
    flex_note = (
        "Flexible Verbraucher im grauen Bereich: **Soll** aus "
        "`consumer_powers_kw` je Log-Eintrag (Fallback: `consumption_snapshot.flex_kw`)."
    )
    if merge_active:
        slots_note = ""
        if history_slot_count is not None:
            slots_note = f" {history_slot_count} Viertelstunden-Slots aus dem Log."
        merge_note = (
            "**Merge-Pfad aktiv:** Chart und Tabelle nutzen dieselben Zeilen aus "
            f"`build_chart_display_context` (Produktiv-Log + MILP-Tail).{slots_note}"
        )
    else:
        merge_note = (
            "**Kein Merge-Pfad:** nur MILP-Simulation (`optimized_df`) — "
            "Produktiv-Log wird für Chart/Tabelle nicht eingemischt."
        )
    return (
        f"**Datenbasis Produktiv-Log** — {runtime_note}. {file_note}{legacy_note} "
        f"{flex_note} {merge_note}"
    )


def render_display_data_basis_expander(
    log_source: optimization_history.ProductionLogSourceInfo,
    *,
    merge_active: bool,
    history_slot_count: int | None = None,
) -> None:
    """Datenbasis-Hinweis vor Chart/Tabelle — eingeklappt nur Log-Pfad."""
    with st.expander(format_display_data_basis_path(log_source), expanded=False):
        st.markdown(
            format_display_data_basis_caption(
                log_source,
                merge_active=merge_active,
                history_slot_count=history_slot_count,
            )
        )


def _quality_at_row(row_index, frame_index: pd.Index, qualities: tuple[str, ...]) -> str:
    position = int(frame_index.get_loc(row_index))
    return qualities[position]


def _style_simulation_table(
    df: pd.DataFrame,
    slot_qualities: tuple[str, ...],
) -> pd.io.formats.style.Styler:
    """
    Zeilen-Hintergrund für fehlende Log-Slots (orange).

    Wird als Pandas-Styler in die HTML-Tabelle (Freeze-Panes) übernommen.
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
    display_df = _format_simulation_table_numbers(display_df)
    display_df = display_df[_simulation_table_column_order(list(display_df.columns))]

    if slot_qualities is not None:
        styler = _style_simulation_table(display_df, slot_qualities)
    else:
        styler = display_df.style
    render_frozen_simulation_table(styler)


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
    chart_zones = chart_context.zones if chart_context else None
    merge_active = False
    history_slot_count: int | None = None
    if chart_context is not None and optimization_matrix is not None:
        merge_active = True
        savings_view = savings_view_for_chart(
            savings_info,
            optimization_matrix,
            chart_context.chart_window,
        )
        display_ctx = build_chart_display_context(
            chart_context,
            optimized_df.to_dict("records"),
        )
        is_live_segment = (
            chart_context.cycle_offset == 0 and chart_context.segment_index == 0
        )
        zone_now = (
            chart_context.now
            if is_live_segment
            else chart_context.chart_window.end
        )
        chart_zones = ui_chart_zones(
            zone_now,
            chart_context.chart_window,
            sim_rows=optimized_df.to_dict("records"),
            is_live_segment=is_live_segment,
            slot_datetimes=display_ctx.slot_datetimes,
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
        history_slot_count = display_ctx.history_slot_count
        if matched_baseline_df is not None and not display_ctx.history_only:
            display_matched = pd.DataFrame(
                align_rows_to_display_slots(
                    matched_baseline_df.to_dict("records"),
                    display_ctx.slot_datetimes,
                )
            )
            if chart_qualities is not None:
                display_matched = _mask_missing_log_slots(
                    display_matched, chart_qualities
                )
        elif display_ctx.history_only:
            display_matched = None
        sun_markers = build_sun_markers(
            chart_context.chart_window,
            chart_context.now,
            chart_context.planning_window,
            slot_datetimes=display_ctx.slot_datetimes,
        )

    log_source = None
    if chart_context is not None:
        log_source = optimization_history.describe_production_log_source()

    matched_cost, optimized_cost = _cost_totals_from_savings(savings_view)
    if log_source is not None:
        render_display_data_basis_expander(
            log_source,
            merge_active=merge_active,
            history_slot_count=history_slot_count,
        )
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
        chart_zones=chart_zones,
        sun_markers=sun_markers,
        slot_qualities=chart_qualities,
        history_slot_count=history_slot_count,
    )
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
    render_applied_targets(savings_view)


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
