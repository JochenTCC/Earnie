"""Plotly-Charts für Optimierungsdarstellung (sunrise→sunrise Live, 24h Historie)."""
from __future__ import annotations

from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data.planning_window import UiChartWindow
from optimizer.deviation_eval import DeviationEvent
from ui.chart_decorations import (
    ChartSunMarkers,
    _CHART2_S2_HELP,
    _CHART2_S2_TITLE,
    _add_cost_summary_annotations,
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
from ui.chart_cumulative import (
    add_cumulative_consumption_traces,
    add_cumulative_cost_traces,
    add_cumulative_s2_split_traces,
)
from ui.chart_slot_axis import ChartSlotAxis, _chart_xaxis_config
from ui.chart_soc import (
    add_baseline_soc_traces,
    add_entladesperre_soc_band_traces,
    add_optimized_soc_trace,
    add_price_on_soc_axis_trace,
    _soc_at_chart_now,
)
from ui.chart_trace_segments import _extrapolation_bounds
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
) -> None:
    active_consumers = ordered_active_consumers_for_stack(
        df,
        matrix=matrix,
        chart_window=chart_window,
    )
    if "PV-Prognose (kW)" in df.columns:
        _add_pv_trace(fig, axis, df["PV-Prognose (kW)"], df["Uhrzeit"])

    from ui.chart_flow_balance import (
        add_flow_balance_traces,
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


def build_power_soc_chart_figure(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
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
) -> go.Figure:
    """Baut Chart 1 (Leistung, SoC, Preis) ohne Streamlit-Rendering."""
    plot_df = _mask_missing_log_slots(df, slot_qualities)
    bar_colors = get_bar_colors(plot_df)
    axis = ChartSlotAxis.from_dataframe(plot_df)
    extrap_start, extrap_end = _extrapolation_bounds(plot_df)
    range_start = _chart_range_start(chart_window)
    fig = go.Figure()

    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis, range_start=range_start)
    _add_missing_slot_backgrounds(fig, axis, slot_qualities)

    add_power_traces(
        fig,
        plot_df,
        bar_colors,
        axis,
        extrap_start,
        extrap_end,
        matrix=optimization_matrix,
        chart_window=chart_window,
        chart_zones=chart_zones,
    )
    add_entladesperre_soc_band_traces(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end,
    )
    add_optimized_soc_trace(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end,
        history_slot_count=history_slot_count,
        chart_now=chart_now,
    )
    if show_baseline_soc:
        soc_at_now = _soc_at_chart_now(
            axis, plot_df, chart_now, history_slot_count,
        )
        add_baseline_soc_traces(
            fig,
            matched_baseline_df,
            extrap_start=extrap_start,
            extrap_end=extrap_end,
            chart_now=chart_now,
            history_slot_count=history_slot_count,
            soc_at_now=soc_at_now,
        )
    add_price_on_soc_axis_trace(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end
    )

    if sun_markers is not None:
        _add_sun_markers(fig, sun_markers)
    _add_deviation_markers(fig, axis, plot_df, slot_deviation_events)

    default_title = (
        _sunrise_chart_title(chart_window)
        if chart_window is not None
        else "24-Stunden-Zeithorizont (Leistung, SoC & Preis)"
    )
    plotly_title = None if chart_header_label else chart_title or default_title
    layout_title = plotly_title if plotly_title else ""
    top_margin = 20 if chart_header_label else 50
    fig.update_layout(
        title=layout_title,
        xaxis=_chart_xaxis_config(axis, range_start=range_start),
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
    return fig


def render_power_soc_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
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
    )
    plotly_kwargs: dict = {"width": "stretch"}
    if chart_key:
        plotly_kwargs["key"] = chart_key
    inject_mobile_legend_css()
    st.plotly_chart(fig, **plotly_kwargs)
    render_collapsible_legend_from_figure(fig)


def render_cumulative_cost_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
    *,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
) -> None:
    """Kumulierte Stromkosten und Verbrauch BL Ziel vs. optimiert."""
    axis = ChartSlotAxis.from_dataframe(df)
    extrap_start, extrap_end = _extrapolation_bounds(df)
    range_start = _chart_range_start(chart_window)
    fig = go.Figure()
    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis, range_start=range_start)
    _add_missing_slot_backgrounds(fig, axis, slot_qualities)
    length = len(axis.starts)
    split_mode = (
        history_slot_count is not None
        and history_slot_count > 0
        and slot_actual_cost_euro is not None
        and slot_actual_consumption_kwh is not None
    )
    has_costs = bool(hourly_matched_baseline_cost_euro and hourly_optimized_cost_euro)
    has_consumption = bool(
        hourly_matched_baseline_consumption_kwh and hourly_optimized_consumption_kwh
    )
    if split_mode:
        add_cumulative_s2_split_traces(
            fig,
            df["Uhrzeit"],
            axis,
            history_slot_count=history_slot_count,
            slot_actual_cost_euro=slot_actual_cost_euro or [],
            slot_actual_consumption_kwh=slot_actual_consumption_kwh or [],
            hourly_matched_baseline_cost_euro=hourly_matched_baseline_cost_euro or [],
            hourly_optimized_cost_euro=hourly_optimized_cost_euro or [],
            hourly_matched_baseline_consumption_kwh=(
                hourly_matched_baseline_consumption_kwh or []
            ),
            hourly_optimized_consumption_kwh=hourly_optimized_consumption_kwh or [],
        )
        has_costs = has_costs or history_slot_count > 0
        has_consumption = has_consumption or history_slot_count > 0
    elif has_costs:
        add_cumulative_cost_traces(
            fig,
            df["Uhrzeit"],
            axis,
            hourly_matched_baseline_cost_euro or [],
            hourly_optimized_cost_euro or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )
    if not split_mode and has_consumption:
        add_cumulative_consumption_traces(
            fig,
            df["Uhrzeit"],
            axis,
            hourly_matched_baseline_consumption_kwh or [],
            hourly_optimized_consumption_kwh or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )

    show_cost_summary = (
        has_costs
        and matched_baseline_cost_euro is not None
        and optimized_cost_euro is not None
    )
    if show_cost_summary:
        _add_cost_summary_annotations(
            fig,
            matched_baseline_cost_euro,
            optimized_cost_euro,
        )

    if split_mode:
        render_title_with_help(_CHART2_S2_TITLE, _CHART2_S2_HELP, key="chart2_s2_help")

    default_title = (
        _CHART2_S2_TITLE
        if chart_window is not None
        else "Kumulierte Kosten & Verbrauch"
    )
    plotly_title = "" if split_mode else default_title
    top_margin = 20 if split_mode else 50
    layout = dict(
        title=plotly_title,
        xaxis=_chart_xaxis_config(axis, range_start=range_start),
        yaxis=dict(title="Kosten (€, kumuliert)"),
        **_collapsible_chart_layout(top_margin=top_margin),
    )
    if has_consumption:
        layout["yaxis2"] = dict(
            title="Verbrauch (kWh, kumuliert)",
            side="right",
            overlaying="y",
            showgrid=False,
        )
    fig.update_layout(**layout)
    if (has_costs or has_consumption) and not split_mode:
        extrap_start, _ = _extrapolation_bounds(df)
        if extrap_start is None:
            st.caption(
                "Durchgezogene Linien: Kosten. Gestrichelte Linien (rechte Achse): "
                "Gesamtverbrauch Grundlast + Flex. BL Ziel: historisches Profil skaliert."
            )
    inject_mobile_legend_css()
    st.plotly_chart(fig, width="stretch")
    render_collapsible_legend_from_figure(fig)


def render_price_savings_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
    *,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
) -> None:
    """Alias für kumulierte Kosten- und Verbrauchslinien."""
    render_cumulative_cost_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
        matched_baseline_cost_euro=matched_baseline_cost_euro,
        optimized_cost_euro=optimized_cost_euro,
        chart_window=chart_window,
        chart_now=chart_now,
        chart_zones=chart_zones,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        slot_actual_cost_euro=slot_actual_cost_euro,
        slot_actual_consumption_kwh=slot_actual_consumption_kwh,
    )


def render_optimization_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    hourly_savings_euro: list[float] | None = None,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
    *,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    sun_markers: ChartSunMarkers | None = None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
    chart_header_label: str | None = None,
    chart_header_help: str | None = None,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] | None = None,
) -> None:
    """Zeichnet Leistung/SoC/Preis und kumulierte Kosten/Verbrauch in zwei Charts."""
    render_power_soc_chart(
        df,
        baseline_df,
        matched_baseline_df,
        chart_window=chart_window,
        chart_now=chart_now,
        chart_zones=chart_zones,
        sun_markers=sun_markers,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        chart_key="live_power_soc_chart",
        chart_header_label=chart_header_label,
        chart_header_help=chart_header_help,
        slot_deviation_events=slot_deviation_events,
    )
    render_price_savings_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
        matched_baseline_cost_euro=matched_baseline_cost_euro,
        optimized_cost_euro=optimized_cost_euro,
        chart_window=chart_window,
        chart_now=chart_now,
        chart_zones=chart_zones,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        slot_actual_cost_euro=slot_actual_cost_euro,
        slot_actual_consumption_kwh=slot_actual_consumption_kwh,
    )


# Re-Exports für API-Stabilität (from ui.charts import ...)
from ui.chart_slot_axis import (
    ChartSlotAxis,
    _BAR_CENTER_NUDGE,
    _BATTERY_BAR_WIDTH_FRACTION,
    _EMPTY_FLOAT_SERIES,
    _LINE_ANCHOR_SLOT_CENTER,
    _LINE_ANCHOR_SLOT_START,
    _anchor_fraction_from_legacy_shift,
    _axis_x_bounds,
    _battery_bar_times,
    _chart_time_series,
    _chart_xaxis_config,
    _empty_chart_time_series,
    _forecast_zone_x0,
    _history_zone_x1,
    _hv_line_endpoint_time,
    _line_plot_float,
    _optional_float,
    _safe_float,
    _safe_int_flag,
    _slot_index_at_or_after,
    _slot_index_before,
    _slot_indices_for_hour,
    _slot_time_in_chart,
    _zone_left_edge,
    _zone_right_edge,
    _zone_slot_left,
    _zone_slot_right,
)
from ui.chart_trace_segments import (
    _add_pv_trace,
    _add_segmented_hv_line,
    _bar_hover,
    _bar_widths_ms,
    _extended_hover_labels,
    _extended_line_xy,
    _extrapolation_bounds,
    _hour_prices_from_df,
    _hourly_price_hover_labels,
    _hourly_price_hv_xy,
    _line_hover,
    _price_extrapolated_mask,
    _segment_connected_line_xy,
    _segment_extended_line,
    _segment_hover_labels,
    _segment_linear_connected_line_xy,
    _trace_segments,
)
from ui.chart_decorations import (
    ChartSunMarkers,
    _CHART2_S2_HELP,
    _CHART2_S2_TITLE,
    _COST_SUMMARY_FONT_SIZE,
    _COST_SUMMARY_LINE_SHIFT,
    _COST_SUMMARY_Y_TOP,
    _DEVIATION_MARKER_SIZE,
    _DEVIATION_Y_STACK_FACTOR,
    _add_cost_summary_annotations,
    _add_deviation_markers,
    _add_missing_slot_backgrounds,
    _add_sun_markers,
    _add_zone_backgrounds,
    _anchor_x_in_chart_window,
    _chart_legend,
    _chart_range_start,
    _cost_summary_annotations,
    _mask_missing_log_slots,
    _power_chart_ymax,
    _sunrise_chart_title,
    build_deviation_marker_traces,
    build_sun_markers,
)
from ui.chart_consumer_stack import (
    _CONSUMER_BAR_OPACITY,
    _CONSUMER_IMMEDIATE_CHARGE_PATTERN,
    _CONSUMER_PV_FOLLOW_PATTERN,
    _STACK_ORDER_BY_SA0,
    _active_consumer_bar_columns,
    _appliance_horizon_energy_kwh,
    _chart_has_immediate_charge_bars,
    _chart_has_pv_follow_bars,
    _consumer_bar_marker,
    _consumer_bar_pattern_shapes,
    _consumer_horizon_energy_kwh,
    _consumer_stack_order_ids,
    _is_entladesperre_command,
    _stack_order_cache_key,
    clear_consumer_stack_order_cache,
    get_bar_colors,
    ordered_active_consumers_for_stack,
)
from ui.chart_cumulative import (
    _add_region_cumulative_hv_trace,
    _bridged_forecast_cumulative_series,
    _hourly_cumsum_for_chart,
    _increment_is_finite,
    _region_cumulative_series,
    _sum_slot_increments,
    add_cumulative_actual_traces,
    add_cumulative_consumption_traces,
    add_cumulative_cost_traces,
    add_cumulative_s2_split_traces,
    add_projected_savings_trace,
)
from ui.chart_soc import (
    _ENTLADESPERRE_BAND_HEIGHT_PCT,
    _ENTLADESPERRE_BAND_WIDTH_FRACTION,
    _ENTLADESPERRE_BAND_Y_MIN,
    _apply_soc_current_hour_ramps,
    _apply_soc_intra_hour_ramp,
    _current_hour_soc_ramp,
    _current_hour_soc_ramp_before_now,
    _entladesperre_band_marker,
    _entladesperre_soc_band_bottom,
    _first_milp_slot_in_current_hour,
    _history_battery_kw_for_extrapolation,
    _soc_at_chart_now,
    _soc_from_history_extrapolation,
    _soc_hover_labels_for_times,
    _soc_tail_y_from_row,
    _soc_y_at_moment,
    add_baseline_soc_traces,
    add_entladesperre_soc_band_traces,
    add_optimized_soc_trace,
    add_price_on_soc_axis_trace,
)

__all__ = [
    "ChartSlotAxis",
    "ChartSunMarkers",
    "add_power_traces",
    "build_power_soc_chart_figure",
    "build_sun_markers",
    "build_deviation_marker_traces",
    "clear_consumer_stack_order_cache",
    "get_bar_colors",
    "ordered_active_consumers_for_stack",
    "render_cumulative_cost_chart",
    "render_optimization_chart",
    "render_power_soc_chart",
    "render_price_savings_chart",
]

