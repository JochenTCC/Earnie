"""OptimizationDisplayBundle builders for Live/Historical charts."""
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
    show_soc_plausibility: bool = False


def _apply_backtesting_chart_merge(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    matched_baseline_df: pd.DataFrame | None,
    chart_context: LiveChartContext,
    optimization_matrix: list,
) -> tuple[dict, pd.DataFrame, pd.DataFrame | None, pd.DataFrame]:
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
    display_matched = matched_baseline_df
    if matched_baseline_df is not None:
        display_matched = pd.DataFrame(
            align_rows_to_chart_slots(
                matched_baseline_df.to_dict("records"),
                chart_context.chart_window,
            )
        )
    return savings_view, display_df, display_matched, display_df


def _apply_live_chart_merge(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    matched_baseline_df: pd.DataFrame | None,
    chart_context: LiveChartContext,
    optimization_matrix: list | None,
) -> tuple:
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
    display_df = pd.DataFrame(display_ctx.rows)
    display_matched = matched_baseline_df
    if matched_baseline_df is not None and not display_ctx.history_only:
        display_matched = pd.DataFrame(
            align_rows_to_display_slots(
                matched_baseline_df.to_dict("records"),
                display_ctx.slot_datetimes,
            )
        )
        if display_ctx.slot_qualities is not None:
            display_matched = _mask_missing_log_slots(
                display_matched, display_ctx.slot_qualities
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
    return (
        savings_view,
        display_df,
        display_matched,
        table_df,
        display_ctx.slot_qualities,
        display_ctx.gap_notice,
        chart_zones,
        sun_markers,
        display_ctx.history_slot_count,
        display_ctx.slot_deviation_events,
    )


def _merge_chart_into_bundle(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    matched_baseline_df: pd.DataFrame | None,
    chart_context: LiveChartContext | None,
    optimization_matrix: list | None,
    backtesting_chart: bool,
) -> dict:
    merged = {
        "savings_view": savings_info,
        "display_df": optimized_df,
        "display_matched": matched_baseline_df,
        "table_df": optimized_df,
        "table_qualities": None,
        "table_gap_notice": None,
        "chart_qualities": None,
        "sun_markers": None,
        "chart_zones": chart_context.zones if chart_context else None,
        "merge_active": False,
        "history_slot_count": None,
        "slot_deviation_events": (),
    }
    if chart_context is not None and optimization_matrix is not None and backtesting_chart:
        merged["merge_active"] = True
        (
            merged["savings_view"],
            merged["display_df"],
            merged["display_matched"],
            merged["table_df"],
        ) = _apply_backtesting_chart_merge(
            savings_info,
            optimized_df,
            matched_baseline_df,
            chart_context,
            optimization_matrix,
        )
        return merged
    if chart_context is None:
        return merged
    merged["merge_active"] = True
    (
        merged["savings_view"],
        merged["display_df"],
        merged["display_matched"],
        merged["table_df"],
        merged["table_qualities"],
        merged["table_gap_notice"],
        merged["chart_zones"],
        merged["sun_markers"],
        merged["history_slot_count"],
        merged["slot_deviation_events"],
    ) = _apply_live_chart_merge(
        savings_info,
        optimized_df,
        matched_baseline_df,
        chart_context,
        optimization_matrix,
    )
    merged["chart_qualities"] = merged["table_qualities"]
    return merged


def _resolve_bundle_headers(
    savings_info: dict,
    chart_context: LiveChartContext | None,
    chart_header_label: str | None,
    chart_header_help: str | None,
    show_soc_plausibility: bool,
) -> tuple[float | None, float | None, str | None, str | None]:
    from ui.simulation_results import _cost_totals_from_savings

    matched_cost, optimized_cost = _cost_totals_from_savings(savings_info)
    if chart_header_label is None and chart_context is not None:
        return (
            matched_cost,
            optimized_cost,
            s2_chart_header_label(chart_context),
            s2_zone_help_text(include_soc_plausibility=show_soc_plausibility),
        )
    return matched_cost, optimized_cost, chart_header_label, chart_header_help


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
    show_soc_plausibility: bool = False,
) -> OptimizationDisplayBundle:
    if matched_baseline_df is None and savings_info.get("matched_baseline_rows"):
        matched_baseline_df = pd.DataFrame(savings_info["matched_baseline_rows"])
    merged = _merge_chart_into_bundle(
        savings_info,
        optimized_df,
        matched_baseline_df,
        chart_context,
        optimization_matrix,
        backtesting_chart,
    )
    if chart_context is not None:
        from ui.simulation_results import _store_s2_data_basis_meta

        _store_s2_data_basis_meta(
            merge_active=merged["merge_active"],
            history_slot_count=merged["history_slot_count"],
        )
    matched_cost, optimized_cost, header_label, header_help = _resolve_bundle_headers(
        savings_info,
        chart_context,
        chart_header_label,
        chart_header_help,
        show_soc_plausibility,
    )
    return _make_optimization_display_bundle(
        {
            "savings_info": savings_info,
            "baseline_df": baseline_df,
            "merged": merged,
            "chart_context": chart_context,
            "matched_cost": matched_cost,
            "optimized_cost": optimized_cost,
            "header_label": header_label,
            "header_help": header_help,
            "simulation_table_title": simulation_table_title,
            "optimization_matrix": optimization_matrix,
            "battery_params": battery_params,
            "flex_consumers": flex_consumers,
            "show_soc_plausibility": show_soc_plausibility,
        }
    )


def _make_optimization_display_bundle(parts: dict) -> OptimizationDisplayBundle:
    merged = parts["merged"]
    return OptimizationDisplayBundle(
        savings_info=parts["savings_info"],
        baseline_df=parts["baseline_df"],
        display_df=merged["display_df"],
        display_matched=merged["display_matched"],
        savings_view=merged["savings_view"],
        table_df=merged["table_df"],
        table_qualities=merged["table_qualities"],
        table_gap_notice=merged["table_gap_notice"],
        chart_context=parts["chart_context"],
        chart_zones=merged["chart_zones"],
        sun_markers=merged["sun_markers"],
        chart_qualities=merged["chart_qualities"],
        history_slot_count=merged["history_slot_count"],
        matched_cost=parts["matched_cost"],
        optimized_cost=parts["optimized_cost"],
        chart_header_label=parts["header_label"],
        chart_header_help=parts["header_help"],
        slot_deviation_events=merged["slot_deviation_events"],
        simulation_table_title=parts["simulation_table_title"],
        optimization_matrix=parts["optimization_matrix"],
        battery_params=parts["battery_params"],
        flex_consumers=parts["flex_consumers"],
        show_soc_plausibility=parts["show_soc_plausibility"],
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
        show_soc_plausibility=True,
    )

def _bundle_flex_context(bundle: OptimizationDisplayBundle):
    return chart_flex_consumers_context(
        list(bundle.flex_consumers) if bundle.flex_consumers else None
    )
