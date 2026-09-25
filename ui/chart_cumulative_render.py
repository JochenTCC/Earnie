"""Streamlit render helpers for Chart 2 (cumulative cost / consumption)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.planning_window import UiChartWindow
from ui.chart_cumulative import (
    add_achieved_savings_trace,
    add_cumulative_consumption_traces,
    add_cumulative_cost_traces,
    add_cumulative_s2_split_traces,
)
from ui.chart_decorations import (
    _CHART2_S2_HELP,
    _CHART2_S2_TITLE,
    _add_cost_summary_annotations,
    _add_missing_slot_backgrounds,
    _add_zone_backgrounds,
    _chart_range_start,
    _collapsible_chart_layout,
)
from ui.chart_legend_mobile import (
    inject_mobile_legend_css,
    render_collapsible_legend_from_figure,
)
from ui.chart_slot_axis import ChartSlotAxis, _chart_xaxis_config
from ui.chart_trace_segments import _extrapolation_bounds
from ui.help_hint import render_title_with_help


@dataclass(frozen=True)
class _CumulativeSeries:
    """Slot-aligned Kosten-/Verbrauchsreihen für Chart 2 inklusive Modus-Flags."""

    matched_cost_euro: list[float] | None
    optimized_cost_euro: list[float] | None
    matched_consumption_kwh: list[float] | None
    optimized_consumption_kwh: list[float] | None
    actual_cost_euro: list[float] | None
    actual_consumption_kwh: list[float] | None
    savings_euro: list[float] | None
    history_slot_count: int | None

    @property
    def split_mode(self) -> bool:
        return (
            self.history_slot_count is not None
            and self.history_slot_count > 0
            and self.actual_cost_euro is not None
            and self.actual_consumption_kwh is not None
        )

    @property
    def show_costs(self) -> bool:
        return (
            bool(self.matched_cost_euro and self.optimized_cost_euro)
            or self.split_mode
        )

    @property
    def show_consumption(self) -> bool:
        return (
            bool(self.matched_consumption_kwh and self.optimized_consumption_kwh)
            or self.split_mode
        )


def _add_s2_split_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    series: _CumulativeSeries,
    chart_window: UiChartWindow | None,
) -> None:
    add_cumulative_s2_split_traces(
        fig,
        df["Uhrzeit"],
        axis,
        history_slot_count=series.history_slot_count,
        slot_actual_cost_euro=series.actual_cost_euro or [],
        slot_actual_consumption_kwh=series.actual_consumption_kwh or [],
        hourly_matched_baseline_cost_euro=series.matched_cost_euro or [],
        hourly_optimized_cost_euro=series.optimized_cost_euro or [],
        hourly_matched_baseline_consumption_kwh=series.matched_consumption_kwh or [],
        hourly_optimized_consumption_kwh=series.optimized_consumption_kwh or [],
    )
    if not series.savings_euro or chart_window is None:
        return
    from ui.chart_day_costs import achieved_savings_cumulative_euro

    achieved = achieved_savings_cumulative_euro(
        list(axis.starts),
        series.savings_euro,
        history_slot_count=series.history_slot_count,
        sa0=chart_window.sa0,
        sa1=chart_window.sa1,
        sa2=chart_window.sa2,
    )
    add_achieved_savings_trace(fig, df["Uhrzeit"], axis, achieved)


def _add_cumulative_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    series: _CumulativeSeries,
    chart_window: UiChartWindow | None,
) -> None:
    extrap_start, extrap_end = _extrapolation_bounds(df)
    if series.split_mode:
        _add_s2_split_traces(fig, df, axis, series, chart_window)
        return
    if series.show_costs:
        add_cumulative_cost_traces(
            fig,
            df["Uhrzeit"],
            axis,
            series.matched_cost_euro or [],
            series.optimized_cost_euro or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )
    if series.show_consumption:
        add_cumulative_consumption_traces(
            fig,
            df["Uhrzeit"],
            axis,
            series.matched_consumption_kwh or [],
            series.optimized_consumption_kwh or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )


def _cumulative_chart_layout(
    axis: ChartSlotAxis,
    range_start,
    series: _CumulativeSeries,
    chart_window: UiChartWindow | None,
) -> dict:
    default_title = (
        _CHART2_S2_TITLE
        if chart_window is not None
        else "Kumulierte Kosten & Verbrauch"
    )
    plotly_title = "" if series.split_mode else default_title
    top_margin = 20 if series.split_mode else 50
    layout = dict(
        title=plotly_title,
        xaxis=_chart_xaxis_config(axis, range_start=range_start),
        yaxis=dict(title="Kosten (€, kumuliert)"),
        **_collapsible_chart_layout(top_margin=top_margin),
    )
    if series.show_consumption:
        layout["yaxis2"] = dict(
            title="Verbrauch (kWh, kumuliert)",
            side="right",
            overlaying="y",
            showgrid=False,
        )
    return layout


def _render_cumulative_figure(
    fig: go.Figure,
    df: pd.DataFrame,
    series: _CumulativeSeries,
    chart_key: str | None,
) -> None:
    if (series.show_costs or series.show_consumption) and not series.split_mode:
        extrap_start, _ = _extrapolation_bounds(df)
        if extrap_start is None:
            st.caption(
                "Durchgezogene Linien: Kosten. Gestrichelte Linien (rechte Achse): "
                "Gesamtverbrauch Grundlast + Flex. BL Ziel: historisches Profil skaliert."
            )
    inject_mobile_legend_css()
    plotly_kwargs: dict = {"width": "stretch"}
    if chart_key:
        plotly_kwargs["key"] = chart_key
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
    cost_summary_days=None,
    hourly_savings_euro: list[float] | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
    chart_key: str | None = None,
) -> None:
    series = _CumulativeSeries(
        matched_cost_euro=hourly_matched_baseline_cost_euro,
        optimized_cost_euro=hourly_optimized_cost_euro,
        matched_consumption_kwh=hourly_matched_baseline_consumption_kwh,
        optimized_consumption_kwh=hourly_optimized_consumption_kwh,
        actual_cost_euro=slot_actual_cost_euro,
        actual_consumption_kwh=slot_actual_consumption_kwh,
        savings_euro=hourly_savings_euro,
        history_slot_count=history_slot_count,
    )
    axis = ChartSlotAxis.from_dataframe(df)
    range_start = _chart_range_start(chart_window)
    fig = go.Figure()
    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis, range_start=range_start)
    _add_missing_slot_backgrounds(fig, axis, slot_qualities)
    _add_cumulative_traces(fig, df, axis, series, chart_window)

    show_cost_summary = bool(cost_summary_days) or (
        series.show_costs
        and matched_baseline_cost_euro is not None
        and optimized_cost_euro is not None
    )
    if show_cost_summary:
        _add_cost_summary_annotations(
            fig,
            matched_baseline_cost_euro,
            optimized_cost_euro,
            days=cost_summary_days,
        )

    if series.split_mode:
        render_title_with_help(_CHART2_S2_TITLE, _CHART2_S2_HELP, key="chart2_s2_help")

    fig.update_layout(
        **_cumulative_chart_layout(axis, range_start, series, chart_window)
    )
    _render_cumulative_figure(fig, df, series, chart_key)


def render_price_savings_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
    *,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    cost_summary_days=None,
    hourly_savings_euro: list[float] | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
    chart_key: str | None = None,
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
        cost_summary_days=cost_summary_days,
        hourly_savings_euro=hourly_savings_euro,
        chart_window=chart_window,
        chart_now=chart_now,
        chart_zones=chart_zones,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        slot_actual_cost_euro=slot_actual_cost_euro,
        slot_actual_consumption_kwh=slot_actual_consumption_kwh,
        chart_key=chart_key,
    )
