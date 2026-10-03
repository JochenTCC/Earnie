"""Chart1: one SoC line per battery when multi-ESS columns are present."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from ui.chart_colors import COLOR_SOC, soc_color_for_index
from ui.chart_slot_axis import ChartSlotAxis
from ui.chart_soc import add_optimized_soc_traces, discover_ess_soc_series
from ui.charts import build_power_soc_chart_figure

_TZ = ZoneInfo("Europe/Vienna")


def _base_df(*, multi: bool) -> pd.DataFrame:
    start = datetime(2025, 3, 15, 12, 0, tzinfo=_TZ)
    rows = []
    for index in range(4):
        slot = start + timedelta(minutes=15 * index)
        row = {
            "slot_datetime": slot,
            "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
            "Strompreis (Cent/kWh)": 20.0,
            "Preis extrapoliert": False,
            "PV-Prognose (kW)": 2.0,
            "Verbrauch-Prognose (kW)": 1.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": -1.0,
            "Simulierter SoC (%)": 50.0 + index,
            "Steuerbefehl": "Automatik",
        }
        if multi:
            row["Simulierter SoC Haus (%)"] = 40.0 + index
            row["Simulierter SoC Garage (%)"] = 60.0 + index
        rows.append(row)
    return pd.DataFrame(rows)


def test_discover_ess_soc_series_empty_for_single_column():
    assert discover_ess_soc_series(_base_df(multi=False)) == []


def test_discover_ess_soc_series_finds_labels():
    series = discover_ess_soc_series(_base_df(multi=True))
    assert series == [
        ("Simulierter SoC Haus (%)", "SoC · Haus"),
        ("Simulierter SoC Garage (%)", "SoC · Garage"),
    ]


def test_add_optimized_soc_traces_single_battery_keeps_soc_legend():
    df = _base_df(multi=False)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_optimized_soc_traces(fig, df, axis)
    soc_names = [t.name for t in fig.data if str(t.name).startswith("SoC")]
    assert soc_names == ["SoC"]
    assert fig.data[0].line.color == COLOR_SOC


def test_add_optimized_soc_traces_multi_battery_two_lines():
    df = _base_df(multi=True)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_optimized_soc_traces(fig, df, axis)
    by_name = {t.name: t for t in fig.data if str(t.name).startswith("SoC")}
    assert set(by_name) == {"SoC · Haus", "SoC · Garage"}
    assert by_name["SoC · Haus"].yaxis == "y2"
    assert by_name["SoC · Garage"].yaxis == "y2"
    assert by_name["SoC · Haus"].line.color == soc_color_for_index(0)
    assert by_name["SoC · Garage"].line.color == soc_color_for_index(1)


def test_build_power_soc_chart_figure_multi_ess_soc_lines():
    df = _base_df(multi=True)
    fig = build_power_soc_chart_figure(df, show_baseline_soc=False)
    names = {t.name for t in fig.data if str(t.name).startswith("SoC")}
    assert names == {"SoC · Haus", "SoC · Garage"}
