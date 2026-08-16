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
            show_soc_plausibility=bundle.show_soc_plausibility,
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
            "Horizont SA_0-->SA_2 (voller MILP-Plan). BL Profil: historisches Flex-Profil. "
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
            f"`EARNIE_RUNTIME_PATH` = `{log_source.env_runtime_dir}` "
            f"(aufgelöst: `{log_source.runtime_dir}`)"
        )
    else:
        runtime_note = (
            "Keine `EARNIE_RUNTIME_PATH` gesetzt — "
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
        f"**Datenbasis Produktiv-Log** — {runtime_note}. {file_note} "
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
            baseline_same_flex_rows=savings_info.get("baseline_same_flex_rows"),
        )
        live_optimization_debug.save_debug_snapshot(payload, kind=kind)
    except (OSError, TypeError) as exc:
        logger.warning("Debug-Snapshot konnte nicht gespeichert werden: %s", exc)

from ui.simulation_display_bundle import (  # noqa: E402
    OptimizationDisplayBundle,
    _bundle_flex_context,
    build_optimization_display_bundle,
    build_optimization_display_bundle_from_snapshot,
)

# Re-Exports für API-Stabilität (from ui.simulation_results import ...)
__all__ = [
    "OptimizationDisplayBundle",
    "SESSION_LIVE_DISPLAY_BUNDLE",
    "_bundle_flex_context",
    "build_optimization_display_bundle",
    "build_optimization_display_bundle_from_snapshot",
    "format_display_data_basis_caption",
    "format_display_data_basis_path",
    "persist_simulation_debug",
    "render_applied_targets",
    "render_display_data_basis_expander",
    "render_live_display_data_basis_expander",
    "render_optimization_chart1",
    "render_optimization_chart2",
    "render_optimization_results",
    "render_optimization_results_tail",
    "render_simulation_details",
]
