"""Regressionstests für S-2-UI-Chart-Bugs (Backlog Zeile 10ff)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from data.planning_window import (
    compute_ui_chart_window,
    ui_chart_zones,
)
from ui.chart_context import build_chart_display_context, build_live_chart_context
from ui.charts import (
    ChartSlotAxis,
    _add_missing_slot_backgrounds,
    _add_sun_markers,
    _add_zone_backgrounds,
    _zone_right_edge,
    add_optimized_soc_trace,
    build_sun_markers,
)
from runtime_store.history_timeline import SLOT_MISSING

LAT = 47.404
LON = 9.743
TZ = "Europe/Vienna"
_TZ = ZoneInfo(TZ)


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_TZ)


def _mixed_resolution_slots() -> list[datetime]:
    """Viertelstunden 14:00–14:45, danach stündlich (Spec §6)."""
    start = _dt(2026, 6, 15, 14, 0)
    quarters = [start + timedelta(minutes=15 * index) for index in range(4)]
    hours = [_dt(2026, 6, 15, hour, 0) for hour in range(15, 18)]
    return quarters + hours


def test_legacy_index_time_mixed_quarter_and_hour_steps():
    slots = _mixed_resolution_slots()
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))
    assert axis.legacy_index_time(-0.5) == slots[0]
    assert axis.legacy_index_time(3.5) == slots[3] + timedelta(minutes=15)
    assert axis.legacy_index_time(4.5) == _dt(2026, 6, 15, 16, 0)
    assert axis.legacy_index_time(len(slots) - 0.5) == slots[-1] + timedelta(hours=1)


def test_zone_right_edge_at_quarter_to_hour_boundary():
    slots = _mixed_resolution_slots()
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))
    assert _zone_right_edge(axis, _dt(2026, 6, 15, 15, 0)) == _dt(2026, 6, 15, 15, 0)


def test_past_cycle_zones_cover_full_display_window():
    now = _dt(2026, 6, 15, 14, 0)
    chart_context = build_live_chart_context(1, 0, now=now)
    display = build_chart_display_context(chart_context, [])
    chart = chart_context.chart_window
    zones = ui_chart_zones(
        chart.end,
        chart,
        is_live_segment=False,
        slot_datetimes=display.slot_datetimes,
    )
    assert zones.history.fill_color is not None
    assert zones.forecast.fill_color is None
    assert zones.history.end == chart.end + timedelta(hours=1)
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(display.slot_datetimes)})
    )
    x_left, x_right = axis.x_range(range_start=chart.start)
    assert _zone_right_edge(axis, zones.history.end) == x_right


def test_gray_zone_aligns_with_sa0_at_left_axis():
    now = _dt(2026, 6, 15, 14, 0)
    chart_context = build_live_chart_context(0, 0, now=now)
    chart = chart_context.chart_window
    display = build_chart_display_context(chart_context, [])
    zones = ui_chart_zones(
        now, chart, is_live_segment=True, slot_datetimes=display.slot_datetimes
    )
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(display.slot_datetimes)})
    )
    x_left, _ = axis.x_range(range_start=chart.start)
    fig = go.Figure()
    _add_zone_backgrounds(fig, zones, axis, range_start=chart.start)
    assert x_left == chart.start
    assert display.slot_datetimes[0] < chart.start
    assert fig.layout.shapes[0].x0 == x_left


def test_build_sun_markers_omits_sunset():
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0)
    markers = build_sun_markers(chart, now, planning_window=None)
    assert markers.sunset_xs == ()


def test_add_sun_markers_only_now_and_sa():
    fig = go.Figure()
    markers = build_sun_markers(
        compute_ui_chart_window(_dt(2026, 6, 15, 14, 0), LAT, LON, TZ),
        _dt(2026, 6, 15, 14, 0),
        planning_window=None,
    )
    _add_sun_markers(fig, markers)
    annotations = [
        shape.get("annotation_text", "")
        for shape in fig.layout.shapes or []
        if hasattr(shape, "annotation_text")
    ]
    assert not any(text.startswith("SU") for text in annotations if text)


def test_missing_slot_backgrounds_align_with_mixed_axis():
    slots = _mixed_resolution_slots()
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))
    qualities = tuple(SLOT_MISSING if index == 1 else "present" for index in range(len(slots)))
    fig = go.Figure()
    _add_missing_slot_backgrounds(fig, axis, qualities)
    assert len(fig.layout.shapes) == 1
    shape = fig.layout.shapes[0]
    assert shape.x0 == axis.legacy_index_time(0.5)
    assert shape.x1 == axis.legacy_index_time(1.5)


def test_soc_trace_splits_at_history_boundary():
    slots = _mixed_resolution_slots()[:6]
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Simulierter SoC (%)": [50.0, 51.0, 52.0, 80.0, 81.0, 82.0],
        "Geplante Batterie-Aktion (kW)": [0.0] * 6,
        "Preis extrapoliert": [False] * 6,
    })
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_optimized_soc_trace(fig, df, axis, history_slot_count=3)
    soc_traces = [trace for trace in fig.data if trace.name == "SoC"]
    assert len(soc_traces) == 2
    assert soc_traces[0].y[-1] == 52.0
    assert soc_traces[1].y[0] == 80.0


def _green_vrect(fig) -> object | None:
    for shape in fig.layout.shapes or []:
        if shape.fillcolor and "76, 175, 80" in str(shape.fillcolor):
            return shape
    return None


def test_green_zone_reaches_axis_edges_live():
    now = _dt(2026, 6, 15, 14, 0)
    chart_context = build_live_chart_context(0, 0, now=now)
    chart = chart_context.chart_window
    sim_rows = [
        {
            "slot_datetime": slot,
            "Preis extrapoliert": slot >= _dt(2026, 6, 15, 18, 0),
        }
        for slot in chart.slot_datetimes
    ]
    display = build_chart_display_context(chart_context, sim_rows)
    zones = ui_chart_zones(
        now,
        chart,
        sim_rows=sim_rows,
        is_live_segment=True,
        slot_datetimes=display.slot_datetimes,
    )
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(display.slot_datetimes)})
    )
    x_left, x_right = axis.x_range(range_start=chart.start)
    fig = go.Figure()
    _add_zone_backgrounds(fig, zones, axis, range_start=chart.start)
    green = _green_vrect(fig)
    assert green is not None
    assert green.x0 == _dt(2026, 6, 15, 18, 0)
    assert green.x0 >= x_left
    assert green.x1 == x_right


def test_green_zone_reaches_axis_edges_sa1_sa2():
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1)
    sim_rows = [
        {
            "slot_datetime": slot,
            "Preis extrapoliert": slot >= _dt(2026, 6, 16, 10, 0),
        }
        for slot in chart.slot_datetimes
    ]
    zones = ui_chart_zones(
        now, chart, sim_rows=sim_rows, slot_datetimes=chart.slot_datetimes
    )
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(chart.slot_datetimes)})
    )
    x_left, x_right = axis.x_range(range_start=chart.start)
    fig = go.Figure()
    _add_zone_backgrounds(fig, zones, axis, range_start=chart.start)
    green = _green_vrect(fig)
    assert green is not None
    assert green.x0 == _dt(2026, 6, 16, 10, 0)
    assert green.x0 >= x_left
    assert green.x1 == x_right


def test_green_zone_x0_clipped_to_sa0_when_extrap_before_window():
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1)
    sim_rows = [
        {
            "slot_datetime": slot,
            "Preis extrapoliert": slot >= chart.slot_datetimes[0],
        }
        for slot in chart.slot_datetimes
    ]
    zones = ui_chart_zones(
        now, chart, sim_rows=sim_rows, slot_datetimes=chart.slot_datetimes
    )
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(chart.slot_datetimes)})
    )
    x_left, x_right = axis.x_range(range_start=chart.start)
    fig = go.Figure()
    _add_zone_backgrounds(fig, zones, axis, range_start=chart.start)
    green = _green_vrect(fig)
    assert green is not None
    assert x_left == chart.start
    assert green.x0 == x_left
    assert green.x1 == x_right


def test_green_zone_left_at_quarter_to_hour_transition():
    now = _dt(2026, 6, 15, 14, 45)
    chart_context = build_live_chart_context(0, 0, now=now)
    chart = chart_context.chart_window
    hour0 = _dt(2026, 6, 15, 14, 0)
    sim_rows = [
        {
            "slot_datetime": slot,
            "Preis extrapoliert": slot >= _dt(2026, 6, 15, 15, 0),
        }
        for slot in chart.slot_datetimes
        if slot >= hour0
    ]
    display = build_chart_display_context(chart_context, sim_rows)
    zones = ui_chart_zones(
        now,
        chart,
        sim_rows=sim_rows,
        is_live_segment=True,
        slot_datetimes=display.slot_datetimes,
    )
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(display.slot_datetimes)})
    )
    x_left, x_right = axis.x_range(range_start=chart.start)
    idx = list(display.slot_datetimes).index(zones.forecast.start)
    fig = go.Figure()
    _add_zone_backgrounds(fig, zones, axis, range_start=chart.start)
    green = _green_vrect(fig)
    assert green is not None
    assert green.x0 == axis.legacy_index_time(idx - 0.5)
    assert green.x1 == x_right


def test_gray_zone_reaches_axis_end_for_past_cycle():
    now = _dt(2026, 6, 15, 14, 0)
    chart_context = build_live_chart_context(1, 0, now=now)
    chart = chart_context.chart_window
    display = build_chart_display_context(chart_context, [])
    zones = ui_chart_zones(
        chart.end,
        chart,
        is_live_segment=False,
        slot_datetimes=display.slot_datetimes,
    )
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(display.slot_datetimes)})
    )
    x_left, x_right = axis.x_range(range_start=chart.start)
    fig = go.Figure()
    _add_zone_backgrounds(fig, zones, axis, range_start=chart.start)
    assert len(fig.layout.shapes) == 1
    assert fig.layout.shapes[0].x0 == x_left
    assert fig.layout.shapes[0].x1 == x_right
