#!/usr/bin/env python3
"""
Exportiert die fiktiven Rauf/Runter-Szenarien als Plotly-HTML.

Erzeugt eine vereinfachte Chart-1-Vorschau (Leistungsbalken + PV/Verbrauch/Netz-Linien).

Aufruf:
    python -m scripts.export_flow_balance_chart_html
    python -m scripts.export_flow_balance_chart_html --open
"""
from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

import plotly.graph_objects as go

from scripts.flow_balance_test_data import flow_balance_scenario_dataframe
from ui.charts import (
    ChartSlotAxis,
    _chart_xaxis_config,
    add_power_traces,
    get_bar_colors,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "runtime" / "flow_balance_preview.html"


def build_flow_balance_preview_figure() -> go.Figure:
    df = flow_balance_scenario_dataframe()
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_power_traces(fig, df, get_bar_colors(df), axis)
    fig.update_layout(
        title="Chart 1 — Rauf/Runter-Szenarien A–H (Vorschau)",
        xaxis=_chart_xaxis_config(axis),
        barmode="overlay",
        yaxis=dict(title="Leistung (kW)", side="left"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=40, r=40, t=60, b=110),
        height=520,
    )
    for index, row in df.iterrows():
        fig.add_annotation(
            x=row["slot_datetime"],
            y=0,
            text=str(row["scenario_id"]),
            showarrow=False,
            yshift=-18,
            font=dict(size=11, color="#555555"),
        )
    return fig


def export_flow_balance_chart_html(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    figure = build_flow_balance_preview_figure()
    figure.write_html(str(target), include_plotlyjs="cdn")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Ziel-HTML (Standard: {DEFAULT_OUTPUT.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="HTML nach dem Export im Standardbrowser öffnen",
    )
    args = parser.parse_args()
    path = export_flow_balance_chart_html(args.output.resolve())
    print(f"Vorschau geschrieben: {path}")
    if args.open:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
