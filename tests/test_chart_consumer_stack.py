"""Gestapelte Flex-Verbraucher in Chart-1-Rauf/Runter-Balken."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

import config
from data.planning_window import UiChartWindow
from ui.charts import (
    ChartSlotAxis,
    _consumer_chart_color,
    _consumer_horizon_energy_kwh,
    add_power_traces,
    clear_consumer_stack_order_cache,
    get_bar_colors,
    ordered_active_consumers_for_stack,
)

_TZ = ZoneInfo("Europe/Vienna")

_TEST_CONSUMERS = (
    {
        "id": "swimspa",
        "name": "SwimSpa",
        "chart_color": "#c2185b",
        "optimizer_enabled": True,
    },
    {
        "id": "eauto",
        "name": "E-Auto",
        "chart_color": "#00bcd4",
        "optimizer_enabled": True,
    },
)


def _patch_consumers(monkeypatch):
    monkeypatch.setattr(
        config,
        "get_flexible_consumers",
        lambda optimizer_only=False: list(_TEST_CONSUMERS),
    )


def _chart_window() -> UiChartWindow:
    sa0 = datetime(2026, 7, 5, 5, 30, tzinfo=_TZ)
    sa1 = datetime(2026, 7, 6, 5, 30, tzinfo=_TZ)
    sa2 = datetime(2026, 7, 7, 5, 30, tzinfo=_TZ)
    slots = tuple(sa0 + timedelta(hours=index) for index in range(3))
    return UiChartWindow(
        start=sa0,
        end=sa1,
        sa0=sa0,
        sa1=sa1,
        sa2=sa2,
        segment_index=0,
        slot_datetimes=slots,
    )


def _matrix_row(slot: datetime, swimspa_kw: float, eauto_kw: float) -> dict:
    return {
        "slot_datetime": slot,
        "SwimSpa (kW)": swimspa_kw,
        "E-Auto (kW)": eauto_kw,
    }


def test_horizon_energy_sums_matrix_rows_within_sa_cycle(monkeypatch):
    _patch_consumers(monkeypatch)
    chart = _chart_window()
    matrix = [
        _matrix_row(chart.sa0, 2.0, 0.0),
        _matrix_row(chart.sa0 + timedelta(hours=1), 2.0, 3.0),
        _matrix_row(chart.sa2 + timedelta(hours=1), 9.0, 9.0),
    ]
    df = pd.DataFrame(matrix)
    energy = _consumer_horizon_energy_kwh(matrix, chart, df)
    assert energy["swimspa"] == 4.0
    assert energy["eauto"] == 3.0


def test_stack_order_largest_energy_first_and_cached_per_sa0(monkeypatch):
    _patch_consumers(monkeypatch)
    clear_consumer_stack_order_cache()
    chart = _chart_window()
    matrix = [
        _matrix_row(chart.sa0, 1.0, 5.0),
        _matrix_row(chart.sa0 + timedelta(hours=1), 1.0, 5.0),
    ]
    df = pd.DataFrame(
        {
            "SwimSpa (kW)": [1.0, 1.0],
            "E-Auto (kW)": [5.0, 5.0],
        }
    )
    first = ordered_active_consumers_for_stack(df, matrix=matrix, chart_window=chart)
    assert [consumer["id"] for consumer, _ in first] == ["eauto", "swimspa"]

    matrix[0]["E-Auto (kW)"] = 0.0
    second = ordered_active_consumers_for_stack(df, matrix=matrix, chart_window=chart)
    assert [consumer["id"] for consumer, _ in second] == ["eauto", "swimspa"]


def test_stack_order_recomputed_for_new_sa0(monkeypatch):
    _patch_consumers(monkeypatch)
    clear_consumer_stack_order_cache()
    chart_a = _chart_window()
    chart_b = UiChartWindow(
        start=chart_a.sa0 + timedelta(days=1),
        end=chart_a.sa1 + timedelta(days=1),
        sa0=chart_a.sa0 + timedelta(days=1),
        sa1=chart_a.sa1 + timedelta(days=1),
        sa2=chart_a.sa2 + timedelta(days=1),
        segment_index=0,
        slot_datetimes=chart_a.slot_datetimes,
    )
    df = pd.DataFrame({"SwimSpa (kW)": [2.0], "E-Auto (kW)": [1.0]})
    matrix_a = [_matrix_row(chart_a.sa0, 1.0, 9.0)]
    matrix_b = [_matrix_row(chart_b.sa0, 9.0, 1.0)]
    order_a = ordered_active_consumers_for_stack(df, matrix=matrix_a, chart_window=chart_a)
    order_b = ordered_active_consumers_for_stack(df, matrix=matrix_b, chart_window=chart_b)
    assert [consumer["id"] for consumer, _ in order_a] == ["eauto", "swimspa"]
    assert [consumer["id"] for consumer, _ in order_b] == ["swimspa", "eauto"]


def test_flow_balance_bars_replace_battery_and_flex_at_same_x(monkeypatch):
    _patch_consumers(monkeypatch)
    clear_consumer_stack_order_cache()
    chart = _chart_window()
    slots = list(chart.slot_datetimes)
    df = pd.DataFrame(
        {
            "slot_datetime": slots,
            "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
            "PV-Prognose (kW)": [0.0] * len(slots),
            "Verbrauch-Prognose (kW)": [0.5] * len(slots),
            "Netzbezug (kW)": [0.5] * len(slots),
            "Geplante Batterie-Aktion (kW)": [1.5, 0.0, 0.0],
            "Steuerbefehl": ["IDLE"] * len(slots),
            "SwimSpa (kW)": [2.0, 0.0, 0.0],
            "E-Auto (kW)": [3.0, 0.0, 0.0],
        }
    )
    matrix = [_matrix_row(slots[0], 2.0, 3.0)]
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_power_traces(
        fig,
        df,
        get_bar_colors(df),
        axis,
        matrix=matrix,
        chart_window=chart,
    )
    bar_traces = [trace for trace in fig.data if isinstance(trace, go.Bar)]
    flex_traces = [trace for trace in bar_traces if trace.name in ("SwimSpa", "E-Auto")]
    assert not any(trace.name == "Batterie" for trace in fig.data)
    assert len(flex_traces) == 2
    assert all(float(y) <= 0.0 for trace in flex_traces for y in trace.y)
    assert flex_traces[0].x[0] == flex_traces[1].x[0]
    baseload = next(trace for trace in bar_traces if trace.name == "Grundlast")
    assert flex_traces[0].x[0] == baseload.x[0]


def test_consumer_chart_color_uses_config_when_set(monkeypatch):
    _patch_consumers(monkeypatch)
    consumers = list(_TEST_CONSUMERS)
    consumers[1] = {**consumers[1], "chart_color": None}
    monkeypatch.setattr(
        config,
        "get_flexible_consumers",
        lambda optimizer_only=False: consumers,
    )
    assert _consumer_chart_color(consumers[0]) == "#c2185b"
