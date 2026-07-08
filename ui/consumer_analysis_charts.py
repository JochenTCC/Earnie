"""Plotly-Charts für die Swimspa-Verbraucheranalyse."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.charts import ChartSlotAxis, _add_zone_backgrounds, _chart_legend, _chart_xaxis_config


def _axis_for_df(df: pd.DataFrame) -> ChartSlotAxis:
    return ChartSlotAxis.from_dataframe(df)


def _render_zone_line_chart(
    df: pd.DataFrame,
    traces: list[tuple[str, str]],
    *,
    title: str,
    y_title: str,
    chart_zones,
) -> None:
    if df.empty:
        st.info("Keine Daten für diesen Chart.")
        return
    axis = _axis_for_df(df)
    fig = go.Figure()
    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis)
    x_values = axis.at(slice(None), 0.5)
    for column, name in traces:
        if column not in df.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=df[column],
                name=name,
                mode="lines",
                connectgaps=False,
            )
        )
    fig.update_layout(
        title=title,
        xaxis=_chart_xaxis_config(axis),
        yaxis=dict(title=y_title),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=50, b=110),
    )
    st.plotly_chart(fig, width="stretch")


def render_swimspa_temperature_chart(df: pd.DataFrame, *, chart_zones) -> None:
    _render_zone_line_chart(
        df,
        [("Ist (°C)", "Ist"), ("Soll (°C)", "Soll")],
        title="Swimspa Temperatur",
        y_title="Temperatur (°C)",
        chart_zones=chart_zones,
    )


def render_swimspa_filter_chart(df: pd.DataFrame, *, chart_zones) -> None:
    if df.empty:
        st.info("Keine Filter-Daten.")
        return
    axis = _axis_for_df(df)
    fig = go.Figure()
    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis)
    x_values = axis.at(slice(None), 0.5)
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=df["Autonom (kW)"],
            name="Autonom",
            marker_color="rgba(80, 160, 220, 0.75)",
        )
    )
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=df["Ernie (kW)"],
            name="Ernie-initiiert",
            marker_color="rgba(220, 140, 60, 0.75)",
        )
    )
    fig.update_layout(
        title="Swimspa Filterung",
        barmode="stack",
        xaxis=_chart_xaxis_config(axis),
        yaxis=dict(title="Leistung (kW)"),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=50, b=110),
    )
    st.plotly_chart(fig, width="stretch")
