"""Tests für die mobile Cockpit-Legende."""
from __future__ import annotations

import plotly.graph_objects as go

from ui.chart_legend_mobile import legend_entries_from_figure


def test_legend_entries_respect_showlegend_and_deduplicate_groups():
    fig = go.Figure(
        data=[
            go.Scatter(
                x=[1, 2],
                y=[1, 2],
                name="SoC",
                legendgroup="soc",
                showlegend=True,
                line=dict(color="#00aa00"),
            ),
            go.Scatter(
                x=[1, 2],
                y=[2, 3],
                name="SoC",
                legendgroup="soc",
                showlegend=False,
                line=dict(color="#00aa00"),
            ),
            go.Scatter(
                x=[1, 2],
                y=[3, 4],
                name="Preis",
                showlegend=True,
                line=dict(color="rgb(255, 0, 0)"),
            ),
            go.Scatter(
                x=[1, 2],
                y=[4, 5],
                name="Hidden",
                showlegend=False,
                line=dict(color="#000000"),
            ),
        ]
    )

    entries = legend_entries_from_figure(fig)

    assert entries == [
        ("SoC", "#00aa00"),
        ("Preis", "rgb(255, 0, 0)"),
    ]


def test_legend_entries_use_marker_color_for_bars():
    fig = go.Figure(
        data=[
            go.Bar(
                x=[None],
                y=[None],
                name="SwimSpa",
                legendgroup="flex:swimspa",
                showlegend=True,
                marker=dict(color="rgba(120, 80, 200, 0.9)"),
                visible="legendonly",
            ),
        ]
    )

    entries = legend_entries_from_figure(fig)

    assert entries == [("SwimSpa", "rgba(120, 80, 200, 0.9)")]


def test_legend_entries_preserve_plotly_trace_order():
    fig = go.Figure(
        data=[
            go.Bar(x=[1], y=[1], name="PV", marker=dict(color="#ffcc00"), showlegend=True),
            go.Scatter(
                x=[1],
                y=[1],
                name="SoC",
                line=dict(color="#118844"),
                showlegend=True,
            ),
            go.Scatter(
                x=[1],
                y=[1],
                name="Preis",
                line=dict(color="#cc0000"),
                showlegend=True,
            ),
        ]
    )

    names = [name for name, _color in legend_entries_from_figure(fig)]

    assert names == ["PV", "SoC", "Preis"]
