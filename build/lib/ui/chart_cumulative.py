"""Kumulierte Kosten- und Verbrauchs-Traces."""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go

from ui.chart_colors import (
    COLOR_COST_ACTUAL,
    COLOR_COST_BASELINE,
    COLOR_COST_OPTIMIZED,
    COLOR_COST_SAVINGS,
)
from ui.chart_slot_axis import ChartSlotAxis
from ui.chart_trace_segments import (
    _add_segmented_hv_line,
    _trace_segments,
)

def _hourly_cumsum_for_chart(
    hourly_values: list[float],
    slot_count: int,
) -> pd.Series | None:
    """Kumulierte Stundenreihe mit Länge slot_count (0-Padding bei kürzerer Liste)."""
    if not hourly_values or slot_count <= 0:
        return None
    padded = list(hourly_values[:slot_count])
    if len(padded) < slot_count:
        padded.extend([0.0] * (slot_count - len(padded)))
    return pd.Series(padded, dtype=float).cumsum()


def _increment_is_finite(value: float | None) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isnan(number)


def _region_cumulative_series(
    increments: list[float],
    length: int,
    region_start: int,
    region_end: int,
) -> pd.Series | None:
    """Kumulierte Slot-Reihe nur in [region_start, region_end); fehlende Slots = NaN."""
    if region_start >= region_end or region_end > length:
        return None
    values = [float("nan")] * length
    total = 0.0
    for index in range(region_start, region_end):
        increment = increments[index] if index < len(increments) else float("nan")
        if not _increment_is_finite(increment):
            values[index] = float("nan")
            continue
        total += float(increment)
        values[index] = total
    if not any(_increment_is_finite(values[i]) for i in range(region_start, region_end)):
        return None
    return pd.Series(values, dtype=float)


def _bridged_forecast_cumulative_series(
    forecast_increments: list[float],
    history_increments: list[float],
    length: int,
    region_start: int,
    region_end: int,
) -> pd.Series | None:
    """
    Prognose-Kumulation ab Log-Grenze, fortgesetzt ab Ist-Summe im grauen Bereich.

    Setzt einen Ankerpunkt bei region_start - 1 für die visuelle Brücke grau → neutral.
    """
    if region_start >= region_end or region_end > length:
        return None
    offset = _sum_slot_increments(history_increments, 0, region_start)
    values = [float("nan")] * length
    if region_start > 0:
        values[region_start - 1] = offset
    total = offset
    has_value = region_start > 0 and _increment_is_finite(offset)
    for index in range(region_start, region_end):
        increment = (
            forecast_increments[index]
            if index < len(forecast_increments)
            else float("nan")
        )
        if not _increment_is_finite(increment):
            values[index] = float("nan")
            continue
        total += float(increment)
        values[index] = total
        has_value = True
    if not has_value:
        return None
    return pd.Series(values, dtype=float)


def _sum_slot_increments(
    increments: list[float] | None,
    region_start: int,
    region_end: int,
) -> float:
    if not increments:
        return 0.0
    total = 0.0
    for index in range(region_start, min(region_end, len(increments))):
        increment = increments[index]
        if _increment_is_finite(increment):
            total += float(increment)
    return total


def _add_region_cumulative_hv_trace(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    increments: list[float],
    region_start: int,
    region_end: int,
    *,
    name: str,
    line_kwargs: dict,
    yaxis: str = "y",
    y_format: str = ".3f",
    segment_hover_template: str,
    bridge_left: bool = True,
    history_increments: list[float] | None = None,
) -> None:
    length = len(axis.starts)
    if history_increments is not None:
        cumulative = _bridged_forecast_cumulative_series(
            increments,
            history_increments,
            length,
            region_start,
            region_end,
        )
    else:
        cumulative = _region_cumulative_series(
            increments, length, region_start, region_end
        )
    if cumulative is None:
        return
    segments = [(region_start, region_end, False)]
    _add_segmented_hv_line(
        fig,
        axis,
        cumulative,
        uhrzeit,
        segments,
        name=name,
        line_kwargs=line_kwargs,
        yaxis=yaxis,
        y_format=y_format,
        segment_hover_template=segment_hover_template,
        bridge_left=bridge_left,
    )


def add_cumulative_s2_split_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    *,
    history_slot_count: int,
    slot_actual_cost_euro: list[float],
    slot_actual_consumption_kwh: list[float],
    hourly_matched_baseline_cost_euro: list[float],
    hourly_optimized_cost_euro: list[float],
    hourly_matched_baseline_consumption_kwh: list[float],
    hourly_optimized_consumption_kwh: list[float],
) -> None:
    """Chart 2 S-2: Ist (Log) und Prognose (MILP) mit Brücke an der grau/neutral-Grenze."""
    length = len(axis.starts)
    split = history_slot_count
    if split <= 0 or split > length:
        return

    if split < length:
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_matched_baseline_cost_euro,
            split,
            length,
            name="Kosten BL Ziel (Prognose)",
            line_kwargs=dict(color=COLOR_COST_BASELINE, width=2.5, shape="hv"),
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Kosten BL Ziel (Prognose, kumuliert): "
                "%{y:.3f} €<extra></extra>"
            ),
            history_increments=slot_actual_cost_euro,
        )
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_optimized_cost_euro,
            split,
            length,
            name="Kosten optimiert (Prognose)",
            line_kwargs=dict(color=COLOR_COST_OPTIMIZED, width=2.5, shape="hv"),
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Kosten optimiert (Prognose, kumuliert): "
                "%{y:.3f} €<extra></extra>"
            ),
            history_increments=slot_actual_cost_euro,
        )
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_matched_baseline_consumption_kwh,
            split,
            length,
            name="Verbrauch BL Ziel (Prognose)",
            line_kwargs=dict(color=COLOR_COST_BASELINE, width=2.5, dash="dash", shape="hv"),
            yaxis="y2",
            y_format=".2f",
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Verbrauch BL Ziel (Prognose, kumuliert): "
                "%{y:.2f} kWh<extra></extra>"
            ),
            history_increments=slot_actual_consumption_kwh,
        )
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_optimized_consumption_kwh,
            split,
            length,
            name="Verbrauch optimiert (Prognose)",
            line_kwargs=dict(color=COLOR_COST_OPTIMIZED, width=2.5, dash="dash", shape="hv"),
            yaxis="y2",
            y_format=".2f",
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Verbrauch optimiert (Prognose, kumuliert): "
                "%{y:.2f} kWh<extra></extra>"
            ),
            history_increments=slot_actual_consumption_kwh,
        )

    _add_region_cumulative_hv_trace(
        fig,
        uhrzeit,
        axis,
        slot_actual_cost_euro,
        0,
        split,
        name="Kosten (Ist bisher)",
        line_kwargs=dict(color=COLOR_COST_ACTUAL, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten (Ist bisher, kumuliert): "
            "%{y:.3f} €<extra></extra>"
        ),
    )
    _add_region_cumulative_hv_trace(
        fig,
        uhrzeit,
        axis,
        slot_actual_consumption_kwh,
        0,
        split,
        name="Verbrauch (Ist bisher)",
        line_kwargs=dict(color=COLOR_COST_ACTUAL, width=2.5, dash="dash", shape="hv"),
        yaxis="y2",
        y_format=".2f",
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch (Ist bisher, kumuliert): "
            "%{y:.2f} kWh<extra></extra>"
        ),
    )


def add_cumulative_cost_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    hourly_matched_cost_euro: list[float],
    hourly_optimized_cost_euro: list[float],
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierte Stromkosten: BL Ziel und optimiert."""
    length = len(axis.starts)
    matched_cum = _hourly_cumsum_for_chart(hourly_matched_cost_euro, length)
    optimized_cum = _hourly_cumsum_for_chart(hourly_optimized_cost_euro, length)
    if matched_cum is None or optimized_cum is None:
        return
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
        matched_cum,
        uhrzeit,
        segments,
        name="Kosten BL Ziel",
        line_kwargs=dict(color=COLOR_COST_BASELINE, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten BL Ziel (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )
    _add_segmented_hv_line(
        fig,
        axis,
        optimized_cum,
        uhrzeit,
        segments,
        name="Kosten optimiert",
        line_kwargs=dict(color=COLOR_COST_OPTIMIZED, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten optimiert (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )


def add_cumulative_consumption_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    hourly_matched_kwh: list[float],
    hourly_optimized_kwh: list[float],
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierter Gesamtverbrauch (Grundlast + Flex) auf separater Achse."""
    length = len(axis.starts)
    matched_cum = _hourly_cumsum_for_chart(hourly_matched_kwh, length)
    optimized_cum = _hourly_cumsum_for_chart(hourly_optimized_kwh, length)
    if matched_cum is None or optimized_cum is None:
        return
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
        matched_cum,
        uhrzeit,
        segments,
        name="Verbrauch BL Ziel",
        line_kwargs=dict(color=COLOR_COST_BASELINE, width=2.5, dash="dash", shape="hv"),
        yaxis=yaxis,
        y_format=".2f",
        base_opacity=1.0,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch BL Ziel (kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    )
    _add_segmented_hv_line(
        fig,
        axis,
        optimized_cum,
        uhrzeit,
        segments,
        name="Verbrauch optimiert",
        line_kwargs=dict(color=COLOR_COST_OPTIMIZED, width=2.5, dash="dash", shape="hv"),
        yaxis=yaxis,
        y_format=".2f",
        base_opacity=1.0,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch optimiert (kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    )


def add_cumulative_actual_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    slot_costs_euro: list[float],
    slot_consumption_kwh: list[float],
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierte Ist-Kosten und Ist-Verbrauch (Produktiv-Historie)."""
    length = len(axis.starts)
    cost_cum = pd.Series(slot_costs_euro[:length], dtype=float).cumsum()
    kwh_cum = pd.Series(slot_consumption_kwh[:length], dtype=float).cumsum()
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
        cost_cum,
        uhrzeit,
        segments,
        name="Kosten (Ist)",
        line_kwargs=dict(color=COLOR_COST_OPTIMIZED, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten (Ist, kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )
    _add_segmented_hv_line(
        fig,
        axis,
        kwh_cum,
        uhrzeit,
        segments,
        name="Verbrauch (Ist)",
        line_kwargs=dict(color=COLOR_COST_OPTIMIZED, width=2.5, dash="dash", shape="hv"),
        yaxis="y2",
        y_format=".2f",
        base_opacity=1.0,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch (Ist, kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    )


def add_projected_savings_trace(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    projected_savings_cumulative_euro: list[float],
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierte prognostizierte Ersparnis (Produktiv-Historie)."""
    if not projected_savings_cumulative_euro:
        return
    length = len(axis.starts)
    savings_cum = pd.Series(projected_savings_cumulative_euro[:length], dtype=float)
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
        savings_cum,
        uhrzeit,
        segments,
        name="Ersparnis prognostiziert",
        line_kwargs=dict(color=COLOR_COST_SAVINGS, width=2.5, dash="dot", shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Ersparnis prognostiziert (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )

