"""Gestapelte Flex-Verbraucher in Chart-1-Rauf/Runter-Balken."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import pytest

import config
from data.planning_window import UiChartWindow, UiChartZone, UiChartZones
from house_config.planning_flex_bridge import merge_flexible_consumers, planning_consumer_to_milp
from ui.chart_colors import (
    CONSUMER_CHART_SATURATION_MUTED,
    consumer_chart_color,
)
from ui.chart_consumer_stack import (
    _active_consumer_bar_columns,
    chart_flex_consumers_context,
)
from ui.chart_flow_balance import (
    KIND_FLEX,
    flow_balance_plotly_trace_specs,
    build_flow_balance_slots_from_df,
)
from ui.charts import (
    ChartSlotAxis,
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
        "chart_color_index": 0,
        "optimizer_enabled": True,
    },
    {
        "id": "eauto",
        "name": "E-Auto",
        "chart_color_index": 2,
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


def test_consumer_chart_color_uses_palette_index(monkeypatch):
    _patch_consumers(monkeypatch)
    consumers = list(_TEST_CONSUMERS)
    assert consumer_chart_color(consumers[0]) == consumer_chart_color(
        {"id": "swimspa", "chart_color_index": 0}
    )
    assert consumer_chart_color(consumers[1]) == consumer_chart_color(
        {"id": "eauto", "chart_color_index": 2}
    )


def test_flex_bar_colors_use_zone_saturation(monkeypatch):
    _patch_consumers(monkeypatch)
    chart = _chart_window()
    slots = list(chart.slot_datetimes)
    history_slot = slots[0]
    live_slot = slots[1]
    df = pd.DataFrame(
        {
            "slot_datetime": slots,
            "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
            "PV-Prognose (kW)": [0.0] * len(slots),
            "Verbrauch-Prognose (kW)": [0.0] * len(slots),
            "Netzbezug (kW)": [0.0] * len(slots),
            "Geplante Batterie-Aktion (kW)": [0.0] * len(slots),
            "Steuerbefehl": ["IDLE"] * len(slots),
            "SwimSpa (kW)": [
                2.0 if slot == history_slot else (2.0 if slot == live_slot else 0.0)
                for slot in slots
            ],
            "E-Auto (kW)": [0.0] * len(slots),
        }
    )
    zones = UiChartZones(
        history=UiChartZone(
            label="Vergangenheit",
            start=chart.start,
            end=live_slot,
            fill_color="rgba(0,0,0,0.1)",
        ),
        live_plan=UiChartZone(
            label="Plan",
            start=live_slot,
            end=chart.end,
            fill_color=None,
        ),
        forecast=UiChartZone(
            label="Forecast",
            start=chart.end,
            end=chart.end,
            fill_color=None,
        ),
    )
    flex = ordered_active_consumers_for_stack(df, chart_window=chart)
    flow_slots = build_flow_balance_slots_from_df(df, flex_consumers=flex)
    axis = ChartSlotAxis.from_dataframe(df)
    specs = flow_balance_plotly_trace_specs(
        flow_slots,
        x_values=list(axis.at(slice(0, len(df)), 0.55)),
        uhrzeit=list(df["Uhrzeit"]),
        start=0,
        end=len(df),
        df=df,
        flex_consumers=flex,
        axis=axis,
        chart_zones=zones,
    )
    swimspa = _TEST_CONSUMERS[0]
    full_color = consumer_chart_color(swimspa)
    muted_color = consumer_chart_color(
        swimspa,
        saturation_factor=CONSUMER_CHART_SATURATION_MUTED,
    )
    history_spec = next(
        spec
        for spec in specs
        if spec.kind == KIND_FLEX
        and spec.legendgroup == "flex:swimspa"
        and spec.marker["color"] == full_color
    )
    live_spec = next(
        spec
        for spec in specs
        if spec.kind == KIND_FLEX
        and spec.legendgroup == "flex:swimspa"
        and spec.marker["color"] == muted_color
    )
    assert history_spec.legend_color == full_color
    assert live_spec.legend_color == full_color
    assert len(history_spec.x) == 1
    assert len(live_spec.x) == 1


def test_resolved_flex_from_empty_config_and_planning_bridge(monkeypatch):
    """Bridged house-profile generics appear when config flexible_consumers is empty."""
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=False: [])
    profile_generic = {
        "id": "standard",
        "label": "Standard",
        "type": "generic",
        "nominal_power_kw": 0.3,
        "schedule": {
            "runs_per_week": 7,
            "duration_h": 24.0,
            "start_hour": 0,
            "start_shift_h": 6.0,
        },
    }
    planning = [planning_consumer_to_milp(profile_generic)]
    scenario = {"_planning_flex_consumers": planning}
    from simulation.engine import resolved_flexible_consumers

    merged = resolved_flexible_consumers(scenario, optimizer_only=False)
    assert len(merged) == 1
    assert merged[0]["id"] == "standard"


def test_chart_stack_discovers_bridged_generics_with_bundle_context(monkeypatch):
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=False: [])
    profile_generic = {
        "id": "waschmaschine",
        "label": "Waschmaschine",
        "type": "generic",
        "nominal_power_kw": 2.0,
        "schedule": {
            "runs_per_week": 7,
            "duration_h": 2.0,
            "start_hour": 14,
            "start_shift_h": 8.0,
        },
    }
    flex = merge_flexible_consumers([], [planning_consumer_to_milp(profile_generic)])
    df = pd.DataFrame({"Waschmaschine (kW)": [1.5, 0.0], "Standard (kW)": [0.3, 0.3]})
    with chart_flex_consumers_context(flex):
        active = _active_consumer_bar_columns(df)
    names = {consumer["name"] for consumer, _ in active}
    assert "Waschmaschine" in names
    assert "Standard" in names


def test_chart_stack_fallback_kw_column_when_not_in_registry(monkeypatch):
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=False: [])
    df = pd.DataFrame({"EV (kW)": [3.0, 0.0]})
    with chart_flex_consumers_context([]):
        active = _active_consumer_bar_columns(df)
    assert len(active) == 1
    assert active[0][1] == "EV (kW)"
    assert active[0][0]["name"] == "EV"


def test_flex_consumers_from_snapshot_prefers_meta_list(monkeypatch):
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=False: [])
    stored = [{"id": "ev", "name": "EV", "optimizer_enabled": True}]
    snapshot = {
        "scenario_id": "live",
        "meta": {"_flexible_consumers": stored},
    }
    from simulation.engine import flex_consumers_from_snapshot

    assert flex_consumers_from_snapshot(snapshot) == stored
