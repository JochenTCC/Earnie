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


def test_add_optimized_soc_traces_virtual_ps_uses_slim_line():
    from optimizer.powerstation_soc_chart import (
        HOUSE_SOC_LINE_WIDTH,
        VIRTUAL_SOC_LINE_WIDTH,
    )

    start = datetime(2025, 3, 15, 12, 0, tzinfo=_TZ)
    rows = []
    for index in range(3):
        slot = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "slot_datetime": slot,
                "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
                "Strompreis (Cent/kWh)": 20.0,
                "Preis extrapoliert": False,
                "PV-Prognose (kW)": 2.0,
                "Verbrauch-Prognose (kW)": 1.0,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Netzbezug (kW)": -1.0,
                "Simulierter SoC (%)": 50.0,
                "Simulierter SoC Haus (%)": 50.0 + index,
                "Simulierter SoC VirtPS (%)": 10.0 + index,
                "Steuerbefehl": "Automatik",
            }
        )
    df = pd.DataFrame(rows)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    entities = [
        {"id": "house", "label": "Haus", "virtual": False},
        {"id": "virt", "label": "VirtPS", "virtual": True},
    ]
    add_optimized_soc_traces(fig, df, axis, chart_soc_entities=entities)
    by_name = {t.name: t for t in fig.data if str(t.name).startswith("SoC")}
    assert by_name["SoC · Haus"].line.width == HOUSE_SOC_LINE_WIDTH
    assert by_name["SoC · VirtPS"].line.width == VIRTUAL_SOC_LINE_WIDTH
    assert by_name["SoC · Haus"].line.color == soc_color_for_index(0)
    assert by_name["SoC · VirtPS"].line.color == soc_color_for_index(1)
    assert by_name["SoC · VirtPS"].line.dash not in (None, "solid")


def _y_at(trace, needle: str) -> float | None:
    for x_val, y_val in zip(trace.x, trace.y):
        if needle in str(x_val):
            if y_val != y_val:  # NaN
                return None
            return round(float(y_val), 2)
    return None


def test_powerstation_soc_ramps_stay_on_own_series_not_house():
    """Regression: PS SoC must not snap to house SoC at Jetzt or hour-end.

    Chart1 per-ESS ramps previously anchored every line to primary
    ``Simulierter SoC (%)``, causing a V-dip on physical/virtual PS at Jetzt
    and again at the next hour boundary when ``chart_now`` is in the last QH.
    """
    start = datetime(2026, 10, 14, 13, 0, tzinfo=_TZ)
    chart_now = datetime(2026, 10, 14, 14, 39, tzinfo=_TZ)
    rows = []
    for index in range(12):
        slot = start + timedelta(minutes=15 * index)
        house = 36.0 if index >= 4 else 30.0 + index
        rows.append(
            {
                "slot_datetime": slot,
                "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
                "Strompreis (Cent/kWh)": 20.0,
                "Preis extrapoliert": False,
                "PV-Prognose (kW)": 2.0,
                "Verbrauch-Prognose (kW)": 1.0,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Netzbezug (kW)": -1.0,
                "Simulierter SoC (%)": house,
                "Simulierter SoC 15 kWh (%)": house,
                "Simulierter SoC EcoFlow (%)": 93.4,
                "Simulierter SoC Waschen (%)": 100.0,
                "Simulierter SoC Geschirr (%)": 100.0,
                "Steuerbefehl": "Automatik",
            }
        )
    df = pd.DataFrame(rows)
    hist = next(
        i + 1
        for i, row in enumerate(rows)
        if row["slot_datetime"] == datetime(2026, 10, 14, 14, 0, tzinfo=_TZ)
    )
    entities = [
        {"id": "house", "label": "15 kWh", "virtual": False},
        {"id": "eco", "label": "EcoFlow", "virtual": False},
        {"id": "wasch", "label": "Waschen", "virtual": True},
        {"id": "gs", "label": "Geschirr", "virtual": True},
    ]
    fig = go.Figure()
    add_optimized_soc_traces(
        fig,
        df,
        ChartSlotAxis.from_dataframe(df),
        history_slot_count=hist,
        chart_now=chart_now,
        chart_soc_entities=entities,
    )
    by_name = {t.name: t for t in fig.data if str(t.name).startswith("SoC")}
    eco = by_name["SoC · EcoFlow"]
    wasch = by_name["SoC · Waschen"]
    gs = by_name["SoC · Geschirr"]
    for needle in ("14:39", "15:00"):
        assert _y_at(eco, needle) == 93.4
        assert _y_at(wasch, needle) == 100.0
        assert _y_at(gs, needle) == 100.0
    assert wasch.line.dash != gs.line.dash
    assert wasch.line.dash not in (None, "solid")
    assert gs.line.dash not in (None, "solid")
