"""Plotly-Charts für Optimierungsdarstellung (sunrise→sunrise Live, 24h Historie)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data.planning_window import UiChartWindow
from optimizer.deviation_eval import DeviationEvent
from ui.chart_cumulative_render import (
    render_cumulative_cost_chart,
    render_price_savings_chart,
)
from ui.chart_decorations import (
    ChartSunMarkers,
    _add_deviation_markers,
    _add_missing_slot_backgrounds,
    _add_sun_markers,
    _add_zone_backgrounds,
    _chart_range_start,
    _collapsible_chart_layout,
    _mask_missing_log_slots,
    _sunrise_chart_title,
    build_sun_markers,
)
from ui.chart_consumer_stack import get_bar_colors, ordered_active_consumers_for_stack
from ui.chart_slot_axis import ChartSlotAxis, _chart_xaxis_config
from ui.chart_soc import (
    add_baseline_soc_traces,
    add_ess_mode_soc_underlay_traces,
    add_export_price_on_soc_axis_trace,
    add_optimized_soc_trace,
    add_price_on_soc_axis_trace,
    _soc_at_chart_now,
)
from ui.chart_trace_segments import _add_pv_trace, _extrapolation_bounds
from ui.chart_legend_mobile import (
    inject_mobile_legend_css,
    render_collapsible_legend_from_figure,
)
from ui.help_hint import render_title_with_help

def add_power_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    bar_colors: list[str],
    axis: ChartSlotAxis,
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    *,
    matrix: list[dict] | None = None,
    chart_window: UiChartWindow | None = None,
    chart_zones=None,
    matched_baseline_df: pd.DataFrame | None = None,
    show_soc_plausibility: bool = False,
    history_slot_count: int | None = None,
) -> None:
    from house_config.known_chart_display import apply_known_generic_to_dataframe

    df = apply_known_generic_to_dataframe(df)
    active_consumers = ordered_active_consumers_for_stack(
        df,
        matrix=matrix,
        chart_window=chart_window,
    )
    if "PV-Prognose (kW)" in df.columns:
        _add_pv_trace(fig, axis, df["PV-Prognose (kW)"], df["Uhrzeit"])

    from ui.chart_flow_balance import (
        add_flow_balance_traces,
        add_matched_flex_ghost_traces,
        build_flow_balance_slots_from_df,
    )

    flow_slots = build_flow_balance_slots_from_df(df, flex_consumers=active_consumers)
    add_flow_balance_traces(
        fig,
        df,
        flow_slots,
        axis,
        extrap_start,
        extrap_end,
        flex_consumers=active_consumers,
        chart_zones=chart_zones,
    )
    if show_soc_plausibility:
        add_matched_flex_ghost_traces(
            fig,
            matched_baseline_df,
            axis,
            history_slot_count=history_slot_count,
        )


@dataclass(frozen=True)
class _Chart1Options:
    """Gemeinsame Optionen der Chart-1-Trace-Layer (Leistung, SoC, Preis)."""

    chart_window: UiChartWindow | None
    chart_zones: object | None
    slot_qualities: tuple[str, ...] | None
    matched_baseline_df: pd.DataFrame | None
    optimization_matrix: list[dict] | None
    show_soc_plausibility: bool
    show_baseline_soc: bool
    history_slot_count: int | None
    chart_now: datetime | None
    battery_params: dict | None


def _add_power_layer(
    fig: go.Figure,
    plot_df: pd.DataFrame,
    axis: ChartSlotAxis,
    options: _Chart1Options,
) -> None:
    extrap_start, extrap_end = _extrapolation_bounds(plot_df)
    range_start = _chart_range_start(options.chart_window)
    if options.chart_zones is not None:
        _add_zone_backgrounds(fig, options.chart_zones, axis, range_start=range_start)
    _add_missing_slot_backgrounds(fig, axis, options.slot_qualities)
    add_power_traces(
        fig,
        plot_df,
        get_bar_colors(plot_df),
        axis,
        extrap_start,
        extrap_end,
        matrix=options.optimization_matrix,
        chart_window=options.chart_window,
        chart_zones=options.chart_zones,
        matched_baseline_df=options.matched_baseline_df,
        show_soc_plausibility=options.show_soc_plausibility,
        history_slot_count=options.history_slot_count,
    )


def _add_soc_price_layer(
    fig: go.Figure,
    plot_df: pd.DataFrame,
    axis: ChartSlotAxis,
    options: _Chart1Options,
) -> None:
    extrap_start, extrap_end = _extrapolation_bounds(plot_df)
    add_ess_mode_soc_underlay_traces(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end,
        history_slot_count=options.history_slot_count,
        chart_now=options.chart_now,
        battery_params=options.battery_params,
    )
    add_optimized_soc_trace(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end,
        history_slot_count=options.history_slot_count,
        chart_now=options.chart_now,
        battery_params=options.battery_params,
    )
    if options.show_baseline_soc:
        soc_at_now = _soc_at_chart_now(
            axis, plot_df, options.chart_now, options.history_slot_count,
            battery_params=options.battery_params,
        )
        add_baseline_soc_traces(
            fig,
            options.matched_baseline_df,
            extrap_start=extrap_start,
            extrap_end=extrap_end,
            chart_now=options.chart_now,
            history_slot_count=options.history_slot_count,
            soc_at_now=soc_at_now,
            battery_params=options.battery_params,
        )
    add_price_on_soc_axis_trace(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end
    )
    add_export_price_on_soc_axis_trace(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end
    )


def _power_soc_layout(
    axis: ChartSlotAxis,
    *,
    chart_window: UiChartWindow | None,
    chart_title: str | None,
    chart_header_label: str | None,
) -> dict:
    default_title = (
        _sunrise_chart_title(chart_window)
        if chart_window is not None
        else "24-Stunden-Zeithorizont (Leistung, SoC & Preis)"
    )
    plotly_title = None if chart_header_label else chart_title or default_title
    layout_title = plotly_title if plotly_title else ""
    top_margin = 20 if chart_header_label else 50
    return dict(
        title=layout_title,
        xaxis=_chart_xaxis_config(axis, range_start=_chart_range_start(chart_window)),
        barmode="overlay",
        yaxis=dict(title="Leistung (kW)", side="left"),
        yaxis2=dict(
            title="SoC (%) / Preis (Cent/kWh)",
            side="right",
            overlaying="y",
            showgrid=False,
            range=[-5, 105],
        ),
        **_collapsible_chart_layout(top_margin=top_margin),
    )


def build_power_soc_chart_figure(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
    show_soc_plausibility: bool = False,
    chart_title: str | None = None,
    show_baseline_soc: bool = True,
    chart_window: UiChartWindow | None = None,
    chart_zones=None,
    sun_markers: ChartSunMarkers | None = None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    chart_header_label: str | None = None,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] | None = None,
    optimization_matrix: list[dict] | None = None,
    chart_now: datetime | None = None,
    battery_params: dict | None = None,
) -> go.Figure:
    """Baut Chart 1 (Leistung, SoC, Preis) ohne Streamlit-Rendering."""
    options = _Chart1Options(
        chart_window=chart_window,
        chart_zones=chart_zones,
        slot_qualities=slot_qualities,
        matched_baseline_df=matched_baseline_df,
        optimization_matrix=optimization_matrix,
        show_soc_plausibility=show_soc_plausibility,
        show_baseline_soc=show_baseline_soc,
        history_slot_count=history_slot_count,
        chart_now=chart_now,
        battery_params=battery_params,
    )
    plot_df = _mask_missing_log_slots(df, slot_qualities)
    axis = ChartSlotAxis.from_dataframe(plot_df)
    fig = go.Figure()

    _add_power_layer(fig, plot_df, axis, options)
    _add_soc_price_layer(fig, plot_df, axis, options)

    if sun_markers is not None:
        _add_sun_markers(fig, sun_markers)
    _add_deviation_markers(fig, axis, plot_df, slot_deviation_events)

    fig.update_layout(
        **_power_soc_layout(
            axis,
            chart_window=chart_window,
            chart_title=chart_title,
            chart_header_label=chart_header_label,
        )
    )
    return fig


def render_power_soc_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
    show_soc_plausibility: bool = False,
    chart_title: str | None = None,
    show_baseline_soc: bool = True,
    chart_key: str | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    sun_markers: ChartSunMarkers | None = None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    chart_header_label: str | None = None,
    chart_header_help: str | None = None,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] | None = None,
    optimization_matrix: list[dict] | None = None,
    battery_params: dict | None = None,
) -> None:
    """Leistungen (PV, Verbrauch, Batterie, Flex) und SoC-Verläufe."""
    if chart_header_label and chart_header_help:
        render_title_with_help(
            chart_header_label,
            chart_header_help,
            key="s2_zone_help",
        )
    fig = build_power_soc_chart_figure(
        df,
        baseline_df,
        matched_baseline_df,
        show_soc_plausibility=show_soc_plausibility,
        chart_title=chart_title,
        show_baseline_soc=show_baseline_soc,
        chart_window=chart_window,
        chart_zones=chart_zones,
        sun_markers=sun_markers,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        chart_header_label=chart_header_label,
        slot_deviation_events=slot_deviation_events,
        optimization_matrix=optimization_matrix,
        chart_now=chart_now,
        battery_params=battery_params,
    )
    plotly_kwargs: dict = {"width": "stretch"}
    if chart_key:
        plotly_kwargs["key"] = chart_key
    inject_mobile_legend_css()
    st.plotly_chart(fig, **plotly_kwargs)
    render_collapsible_legend_from_figure(fig)


# Facade re-exports used by tests/scripts (not already imported above for Chart-1).
from ui.chart_slot_axis import (
    _LINE_ANCHOR_SLOT_CENTER,
    _LINE_ANCHOR_SLOT_START,
    _battery_bar_times,
    _history_zone_x1,
    _hv_line_endpoint_time,
    _safe_int_flag,
    _zone_right_edge,
)
from ui.chart_trace_segments import (
    _bar_widths_ms,
    _extended_line_xy,
    _hour_prices_from_df,
    _hourly_price_hv_xy,
    _segment_connected_line_xy,
    _segment_linear_connected_line_xy,
)
from ui.chart_decorations import (
    _cost_summary_annotations,
    build_deviation_marker_traces,
)
from ui.chart_consumer_stack import (
    _chart_has_immediate_charge_bars,
    _chart_has_pv_follow_bars,
    _consumer_bar_marker,
    _consumer_bar_pattern_shapes,
    _consumer_horizon_energy_kwh,
    clear_consumer_stack_order_cache,
)
from ui.chart_cumulative import (
    _bridged_forecast_cumulative_series,
    _region_cumulative_series,
    _sum_slot_increments,
    add_cumulative_s2_split_traces,
)
from ui.chart_soc import (
    _soc_from_history_extrapolation,
    _soc_tail_y_from_row,
)

__all__ = [
    "ChartSlotAxis",
    "add_power_traces",
    "build_power_soc_chart_figure",
    "build_sun_markers",
    "build_deviation_marker_traces",
    "clear_consumer_stack_order_cache",
    "get_bar_colors",
    "ordered_active_consumers_for_stack",
    "render_cumulative_cost_chart",
    "render_power_soc_chart",
    "render_price_savings_chart",
]
