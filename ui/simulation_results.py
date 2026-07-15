"""Gemeinsame Darstellung von Simulationsergebnissen (Live + Historisch)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import streamlit as st
import pandas as pd

import config
from data.planning_window import ui_chart_zones
from optimizer.deviation_eval import DeviationEvent
from optimizer.targets import consumer_column_name, consumer_immediate_charge_column_name
from runtime_store import live_optimization_debug
from runtime_store import optimization_history
from runtime_store.history_timeline import (
    SLOT_MISSING,
    SLOT_PRESENT,
)
from ui.chart_consumer_stack import _chart_flex_consumers, chart_flex_consumers_context
from ui.chart_context import (
    LiveChartContext,
    SLOT_MILP,
    align_rows_to_chart_slots,
    align_rows_to_display_slots,
    build_chart_display_context,
    build_display_savings_series,
    live_now,
    s2_chart_header_label,
    savings_view_for_chart,
)
from ui.charts import (
    _mask_missing_log_slots,
    build_sun_markers,
    render_power_soc_chart,
    render_price_savings_chart,
)
from ui.simulation_table_view import render_frozen_simulation_table
from ui.history_navigation import render_s2_nav_buttons, s2_zone_help_text

logger = logging.getLogger("app")

SESSION_LIVE_DISPLAY_BUNDLE = "live_display_bundle"


@dataclass(frozen=True)
class OptimizationDisplayBundle:
    """Vorbereitete Chart-/Tabellen-Daten für Live-Optimierung."""

    savings_info: dict
    baseline_df: pd.DataFrame
    display_df: pd.DataFrame
    display_matched: pd.DataFrame | None
    savings_view: dict
    table_df: pd.DataFrame
    table_qualities: tuple[str, ...] | None
    table_gap_notice: str | None
    chart_context: LiveChartContext | None
    chart_zones: object | None
    sun_markers: object | None
    chart_qualities: tuple[str, ...] | None
    history_slot_count: int | None
    matched_cost: float | None
    optimized_cost: float | None
    chart_header_label: str | None
    chart_header_help: str | None
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...]
    simulation_table_title: str | None
    optimization_matrix: list[dict] | None = None
    battery_params: dict | None = None
    flex_consumers: tuple[dict, ...] | None = None


def build_optimization_display_bundle(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
    simulation_table_title: str | None = "📋 Simulations-Details (Nächste 24 Stunden)",
    chart_context: LiveChartContext | None = None,
    optimization_matrix: list | None = None,
    battery_params: dict | None = None,
    chart_header_label: str | None = None,
    chart_header_help: str | None = None,
    backtesting_chart: bool = False,
    flex_consumers: tuple[dict, ...] | None = None,
) -> OptimizationDisplayBundle:
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
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] = ()
    if chart_context is not None and optimization_matrix is not None and backtesting_chart:
        merge_active = True
        savings_view = savings_view_for_chart(
            savings_info,
            optimization_matrix,
            chart_context.chart_window,
        )
        optimized_rows = align_rows_to_chart_slots(
            optimized_df.to_dict("records"),
            chart_context.chart_window,
        )
        display_df = pd.DataFrame(optimized_rows)
        table_df = display_df
        if matched_baseline_df is not None:
            display_matched = pd.DataFrame(
                align_rows_to_chart_slots(
                    matched_baseline_df.to_dict("records"),
                    chart_context.chart_window,
                )
            )
    elif chart_context is not None:
        merge_active = True
        matrix_rows = optimization_matrix or []
        savings_view = savings_view_for_chart(
            savings_info,
            matrix_rows,
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
            matrix_rows,
            chart_context.chart_window,
            savings_info=savings_info,
        )
        table_df = pd.DataFrame(display_ctx.rows)
        table_qualities = display_ctx.slot_qualities
        chart_qualities = display_ctx.slot_qualities
        table_gap_notice = display_ctx.gap_notice
        display_df = pd.DataFrame(display_ctx.rows)
        history_slot_count = display_ctx.history_slot_count
        slot_deviation_events = display_ctx.slot_deviation_events
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
            show_now=is_live_segment,
        )

    if chart_context is not None:
        _store_s2_data_basis_meta(
            merge_active=merge_active,
            history_slot_count=history_slot_count,
        )

    matched_cost, optimized_cost = _cost_totals_from_savings(savings_info)
    resolved_header_label = chart_header_label
    resolved_header_help = chart_header_help
    if resolved_header_label is None and chart_context is not None:
        resolved_header_label = s2_chart_header_label(chart_context)
        resolved_header_help = s2_zone_help_text()

    return OptimizationDisplayBundle(
        savings_info=savings_info,
        baseline_df=baseline_df,
        display_df=display_df,
        display_matched=display_matched,
        savings_view=savings_view,
        table_df=table_df,
        table_qualities=table_qualities,
        table_gap_notice=table_gap_notice,
        chart_context=chart_context,
        chart_zones=chart_zones,
        sun_markers=sun_markers,
        chart_qualities=chart_qualities,
        history_slot_count=history_slot_count,
        matched_cost=matched_cost,
        optimized_cost=optimized_cost,
        chart_header_label=resolved_header_label,
        chart_header_help=resolved_header_help,
        slot_deviation_events=slot_deviation_events,
        simulation_table_title=simulation_table_title,
        optimization_matrix=optimization_matrix,
        battery_params=battery_params,
        flex_consumers=flex_consumers,
    )


def build_optimization_display_bundle_from_snapshot(
    snapshot: dict,
    *,
    cycle_offset: int,
    segment_index: int,
    now=None,
    simulation_table_title: str | None = "📋 Simulations-Details (Nächste 24 Stunden)",
) -> OptimizationDisplayBundle | None:
    """Display-Bundle aus main.py-Persistenz ohne MILP-Neuberechnung."""
    from runtime_store.live_display_loader import (
        planning_matrix_from_snapshot,
        planning_window_from_snapshot,
        savings_info_from_snapshot,
    )
    from ui.chart_context import build_live_chart_context, live_now

    savings_info = savings_info_from_snapshot(snapshot)
    optimized_rows = savings_info.get("optimized_rows") or []
    if not optimized_rows:
        return None
    optimized_df = pd.DataFrame(optimized_rows)
    baseline_df = pd.DataFrame(savings_info.get("baseline_rows") or [])
    matched_rows = savings_info.get("matched_baseline_rows") or []
    matched_baseline_df = pd.DataFrame(matched_rows) if matched_rows else None
    optimization_matrix = planning_matrix_from_snapshot(snapshot) or None
    planning_window = planning_window_from_snapshot(snapshot)
    moment = now if now is not None else live_now()
    chart_context = build_live_chart_context(
        cycle_offset,
        segment_index,
        now=moment,
        planning_window=planning_window,
        sim_rows=optimized_rows,
    )
    return build_optimization_display_bundle(
        savings_info,
        optimized_df,
        baseline_df,
        matched_baseline_df,
        simulation_table_title=simulation_table_title,
        chart_context=chart_context,
        optimization_matrix=optimization_matrix,
    )


def _bundle_flex_context(bundle: OptimizationDisplayBundle):
    return chart_flex_consumers_context(
        list(bundle.flex_consumers) if bundle.flex_consumers else None
    )


def render_optimization_chart1(
    bundle: OptimizationDisplayBundle,
    *,
    chart_key: str = "live_power_soc_chart",
) -> None:
    with _bundle_flex_context(bundle):
        render_power_soc_chart(
            bundle.display_df,
            bundle.baseline_df,
            bundle.display_matched,
            chart_window=bundle.chart_context.chart_window if bundle.chart_context else None,
            chart_now=bundle.chart_context.zone_reference if bundle.chart_context else None,
            chart_zones=bundle.chart_zones,
            sun_markers=bundle.sun_markers,
            slot_qualities=bundle.chart_qualities,
            history_slot_count=bundle.history_slot_count,
            chart_key=chart_key,
            chart_header_label=bundle.chart_header_label,
            chart_header_help=bundle.chart_header_help,
            slot_deviation_events=bundle.slot_deviation_events,
            optimization_matrix=bundle.optimization_matrix,
            battery_params=bundle.battery_params,
        )


def render_optimization_chart2(
    bundle: OptimizationDisplayBundle,
    *,
    chart_key: str = "live_price_savings_chart",
) -> None:
    render_price_savings_chart(
        bundle.display_df,
        bundle.savings_view.get("hourly_matched_baseline_cost_euro"),
        bundle.savings_view.get("hourly_optimized_cost_euro"),
        bundle.savings_view.get("hourly_matched_baseline_consumption_kwh"),
        bundle.savings_view.get("hourly_optimized_consumption_kwh"),
        matched_baseline_cost_euro=bundle.matched_cost,
        optimized_cost_euro=bundle.optimized_cost,
        chart_window=bundle.chart_context.chart_window if bundle.chart_context else None,
        chart_now=bundle.chart_context.zone_reference if bundle.chart_context else None,
        chart_zones=bundle.chart_zones,
        slot_qualities=bundle.chart_qualities,
        history_slot_count=bundle.history_slot_count,
        slot_actual_cost_euro=bundle.savings_view.get("slot_actual_cost_euro"),
        slot_actual_consumption_kwh=bundle.savings_view.get("slot_actual_consumption_kwh"),
        chart_key=chart_key,
    )


def render_optimization_results_tail(bundle: OptimizationDisplayBundle) -> None:
    with _bundle_flex_context(bundle):
        if bundle.simulation_table_title:
            table_title = bundle.simulation_table_title
            if bundle.chart_context is not None:
                table_title = "📋 Simulations-Details (Sunset-2-Sunset-Fenster)"
            render_simulation_details(
                bundle.table_df,
                title=table_title,
                slot_qualities=bundle.table_qualities,
                gap_notice=bundle.table_gap_notice,
            )
    render_applied_targets(bundle.savings_info)


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

    with st.expander("⚡ Energievergleich Baseline vs. Optimierung"):
        st.caption(
            "Horizont Jetzt→SA₂ (voller MILP-Plan). BL Profil: historisches Flex-Profil. "
            "BL Ziel: gleiche Energie wie die Optimierung (Profil skaliert), ohne Lastverschiebung."
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
    for consumer in _chart_flex_consumers():
        power_col = consumer_column_name(consumer)
        if power_col in columns:
            flex_kw.append(power_col)
        imm_col = consumer_immediate_charge_column_name(consumer)
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
            f"`EARNIE_RUNTIME_DIR` = `{log_source.env_runtime_dir}` "
            f"(aufgelöst: `{log_source.runtime_dir}`)"
        )
    else:
        runtime_note = (
            "Keine `EARNIE_RUNTIME_DIR` gesetzt — "
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
    """Datenbasis-Hinweis — eingeklappt nur Log-Pfad."""
    with st.expander(format_display_data_basis_path(log_source), expanded=False):
        st.markdown(
            format_display_data_basis_caption(
                log_source,
                merge_active=merge_active,
                history_slot_count=history_slot_count,
            )
        )


def _store_s2_data_basis_meta(
    *,
    merge_active: bool,
    history_slot_count: int | None,
) -> None:
    st.session_state["s2_data_basis_meta"] = {
        "merge_active": merge_active,
        "history_slot_count": history_slot_count,
    }


def render_live_display_data_basis_expander() -> None:
    """Datenbasis-Expander für Sunset-2-Sunset (nach Sankey in app.py)."""
    meta = st.session_state.get("s2_data_basis_meta")
    if meta is None:
        return
    log_source = optimization_history.describe_production_log_source()
    render_display_data_basis_expander(
        log_source,
        merge_active=bool(meta["merge_active"]),
        history_slot_count=meta.get("history_slot_count"),
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
    bundle = build_optimization_display_bundle(
        savings_info,
        optimized_df,
        baseline_df,
        matched_baseline_df,
        simulation_table_title=simulation_table_title,
        chart_context=chart_context,
        optimization_matrix=optimization_matrix,
    )
    render_optimization_chart1(bundle)
    if bundle.chart_context is not None:
        render_s2_nav_buttons(now=live_now())
    render_optimization_chart2(bundle)
    render_optimization_results_tail(bundle)


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
