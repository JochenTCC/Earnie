"""Preis und Einspeisepreis auf der SoC-Achse.

Split from ``ui.chart_soc``, which re-exports every name here.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.chart_slot_axis import ChartSlotAxis
from ui.chart_trace_segments import (
    _EXPORT_PRICE_COLUMN,
    _hour_prices_from_df,
    _hourly_price_hover_labels,
    _hourly_price_hv_xy,
)


def add_price_on_soc_axis_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    *,
    column: str = "Strompreis (Cent/kWh)",
    name: str = "Preis",
    line: dict | None = None,
    hover_label: str = "Preis",
) -> None:
    """Preis auf der SoC-Achse — Stufen je Chart-Slot (QH/Stunde), an Slot-Rändern."""
    del extrap_start, extrap_end
    line_style = line if line is not None else dict(color="red", width=2.5, shape="hv")
    line_x, line_y = _hourly_price_hv_xy(axis, df, column=column)
    if line_x.empty:
        return
    slot_prices = _hour_prices_from_df(df, column=column)
    customdata: list[float] = []
    slot_idx = 0
    for x in line_x:
        x_ts = pd.Timestamp(x)
        while slot_idx + 1 < len(slot_prices):
            next_slot = slot_prices[slot_idx + 1][0]
            if x_ts >= pd.Timestamp(next_slot):
                slot_idx += 1
            else:
                break
        customdata.append(slot_prices[slot_idx][1])
    fig.add_trace(go.Scatter(
        x=line_x,
        y=line_y,
        name=name,
        showlegend=True,
        mode="lines",
        line=line_style,
        opacity=1.0,
        yaxis=yaxis,
        text=_hourly_price_hover_labels(df, line_x, column=column),
        customdata=customdata,
        hovertemplate=(
            f"Uhrzeit: %{{text}}<br>{hover_label}: %{{customdata:.2f}} Cent/kWh"
            "<extra></extra>"
        ),
    ))


def add_export_price_on_soc_axis_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Einspeisevergütung auf der SoC-Achse — gestrichelte orange Stufen."""
    add_price_on_soc_axis_trace(
        fig,
        df,
        axis,
        yaxis=yaxis,
        extrap_start=extrap_start,
        extrap_end=extrap_end,
        column=_EXPORT_PRICE_COLUMN,
        name="Einspeisepreis",
        line=dict(color="orange", width=2.5, dash="dash", shape="hv"),
        hover_label="Einspeisepreis",
    )
