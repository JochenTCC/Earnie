"""Chart 1: Entladesperre-Streifenband unter dem SoC-Verlauf."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from optimizer import battery as bat
from ui.charts import (
    ChartSlotAxis,
    _ENTLADESPERRE_BAND_HEIGHT_PCT,
    add_entladesperre_soc_band_traces,
    add_optimized_soc_trace,
    build_power_soc_chart_figure,
)

_TZ = ZoneInfo("Europe/Vienna")


def _slot(hour: int) -> datetime:
    return datetime(2026, 7, 6, hour, 0, tzinfo=_TZ)


def _chart_df(commands: list[str], soc_values: list[float]) -> pd.DataFrame:
    slots = [_slot(h) for h in range(len(commands))]
    return pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "PV-Prognose (kW)": [0.0] * len(slots),
        "Verbrauch-Prognose (kW)": [1.0] * len(slots),
        "Netzbezug (kW)": [0.5] * len(slots),
        "Geplante Batterie-Aktion (kW)": [0.0] * len(slots),
        "Steuerbefehl": commands,
        "Simulierter SoC (%)": soc_values,
        "Preis extrapoliert": [False] * len(slots),
    })


def test_entladesperre_band_only_for_entladesperre_slots():
    commands = [
        bat.steuerbefehl_for_mode(bat.MODE_AUTOMATIK, 0.0),
        bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0),
        bat.steuerbefehl_for_mode(bat.MODE_ZWANGS_LADEN, 2.0),
    ]
    df = _chart_df(commands, [50.0, 60.0, 70.0])
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_entladesperre_soc_band_traces(fig, df, axis)
    band_traces = [trace for trace in fig.data if trace.name == "Entladesperre"]
    assert len(band_traces) == 1
    band = band_traces[0]
    assert band.yaxis == "y2"
    assert len(band.x) == 1
    assert band.y[0] == _ENTLADESPERRE_BAND_HEIGHT_PCT
    assert band.base[0] == 60.0 - _ENTLADESPERRE_BAND_HEIGHT_PCT
    assert band.marker.pattern.shape == "/"


def test_entladesperre_band_drawn_below_soc_trace():
    commands = [bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0)]
    df = _chart_df(commands, [42.0])
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_entladesperre_soc_band_traces(fig, df, axis)
    add_optimized_soc_trace(fig, df, axis)
    assert fig.data[0].name == "Entladesperre"
    assert fig.data[-1].name == "SoC"


def test_entladesperre_band_shrinks_when_soc_near_axis_bottom():
    commands = [bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0)]
    df = _chart_df(commands, [3.0])
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_entladesperre_soc_band_traces(fig, df, axis)
    band = next(trace for trace in fig.data if trace.name == "Entladesperre")
    assert band.base[0] == -1.0
    assert band.y[0] == 4.0


def test_build_power_soc_chart_includes_entladesperre_band():
    commands = [
        bat.steuerbefehl_for_mode(bat.MODE_AUTOMATIK, 0.0),
        bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0),
    ]
    df = _chart_df(commands, [55.0, 58.0])
    fig = build_power_soc_chart_figure(df, show_baseline_soc=False)
    assert any(trace.name == "Entladesperre" for trace in fig.data)
