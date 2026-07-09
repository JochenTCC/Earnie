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
    _history_zone_x1,
    _hour_prices_from_df,
    _zone_right_edge,
    add_baseline_soc_traces,
    add_optimized_soc_trace,
    add_price_on_soc_axis_trace,
    build_sun_markers,
    render_cumulative_cost_chart,
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
    assert zones.history.end == chart.end
    assert zones.live_plan.start <= zones.live_plan.end
    assert zones.forecast.start <= zones.forecast.end
    assert chart.start <= zones.history.end <= chart.end
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": list(display.slot_datetimes)})
    )
    x_left, x_right = axis.x_range(range_start=chart.start)
    history_fills_axis = (
        zones.history.fill_color is not None
        and zones.forecast.fill_color is None
        and zones.live_plan.end <= zones.history.end
    )
    assert history_fills_axis
    assert _history_zone_x1(
        axis,
        zones.history.end,
        x_right=x_right,
        fill_to_axis_end=history_fills_axis,
    ) == x_right


def test_past_cycle_zones_stay_within_chart_window():
    """Vergangenheits-Zyklen: Zonen innerhalb [chart.start, chart.end], keine invertierte Forecast-Zone."""
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
    assert zones.history.start == chart.start
    assert zones.history.end == chart.end
    assert zones.live_plan.start <= zones.live_plan.end <= chart.end
    assert zones.forecast.start <= zones.forecast.end
    assert zones.forecast.end == chart.end
    assert zones.forecast.fill_color is None


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


def test_build_sun_markers_sa0_sa1_in_live_segment():
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0)
    markers = build_sun_markers(chart, now, planning_window=None, show_now=True)
    assert markers.sa0_x == chart.sa0
    assert markers.sa1_x == chart.sa1
    assert markers.sa2_x is None
    assert markers.now_x == now


def test_build_sun_markers_sa1_sa2_in_forecast_segment():
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1)
    markers = build_sun_markers(chart, now, planning_window=None, show_now=False)
    assert markers.sa0_x is None
    assert markers.sa1_x == chart.sa1
    assert markers.sa2_x == chart.sa2
    assert markers.now_x is None


def test_add_sun_markers_shows_sa_labels_not_sunset():
    fig = go.Figure()
    now = _dt(2026, 6, 15, 14, 0)
    markers = build_sun_markers(
        compute_ui_chart_window(now, LAT, LON, TZ),
        now,
        planning_window=None,
    )
    _add_sun_markers(fig, markers)
    annotations = [getattr(item, "text", "") for item in (fig.layout.annotations or [])]
    assert "Jetzt" in annotations
    assert "SA₀" in annotations
    assert "SA₁" in annotations
    assert not any(text.startswith("SU") for text in annotations if text)
    assert "SA (SOC)" not in annotations


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


def _trace_x_vienna(raw_x, tz=_TZ) -> datetime:
    """Plotly-X aus Trace: naive Werte = Planungszeitzone (nicht UTC)."""
    ts = pd.Timestamp(raw_x)
    if ts.tzinfo is None:
        return ts.tz_localize(tz).to_pydatetime()
    return ts.tz_convert(tz).to_pydatetime()


def test_soc_and_price_traces_align_with_slot_datetimes():
    """SOC/Preis-X darf nicht per UTC-Cast gegenüber der Achse verschoben sein (+2 h CEST)."""
    slots = _mixed_resolution_slots()
    rows = []
    for index, slot in enumerate(slots):
        rows.append({
            "slot_datetime": slot,
            "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
            "Simulierter SoC (%)": 40.0 + index,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Strompreis (Cent/kWh)": 20.0 + index,
            "Preis extrapoliert": False,
        })
    df = pd.DataFrame(rows)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_optimized_soc_trace(fig, df, axis)
    add_price_on_soc_axis_trace(fig, df, axis)
    soc_trace = next(trace for trace in fig.data if trace.name == "SoC")
    for index, slot in enumerate(slots):
        expected_x = pd.Timestamp(axis.at(index, 0.0).iloc[0]).tz_convert(_TZ)
        expected_y = float(df.iloc[index]["Simulierter SoC (%)"])
        soc_points = [
            _trace_x_vienna(x)
            for x, y in zip(soc_trace.x, soc_trace.y)
            if float(y) == expected_y
        ]
        assert expected_x in soc_points, f"SoC Slot {slot} fehlt bei x={expected_x}"
    price_trace = next(trace for trace in fig.data if trace.name == "Preis")
    for hour, price in _hour_prices_from_df(df):
        left_idx = next(
            idx for idx, slot in enumerate(slots)
            if pd.Timestamp(slot).tz_convert(_TZ) == pd.Timestamp(hour).tz_convert(_TZ)
        )
        expected_left = pd.Timestamp(
            axis.legacy_index_time(left_idx - 0.5)
        ).tz_convert(_TZ)
        price_points = [
            _trace_x_vienna(x)
            for x, y in zip(price_trace.x, price_trace.y)
            if float(y) == price
        ]
        assert expected_left in price_points, (
            f"Preis {price} Cent für {hour} erwartet ab {expected_left}, "
            f"gefunden {price_points[:4]}"
        )


def test_soc_trace_bridges_at_history_boundary():
    """Keine Lücke am Übergang grau (Log) → neutral (MILP)."""
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
    assert soc_traces[1].y[0] == 52.0
    assert soc_traces[1].y[1] == 80.0


def test_baseline_soc_trace_starts_at_history_boundary_not_in_gray():
    """SoC BL Ziel beginnt an der Log-Grenze, nicht eine Viertelstunde im grauen Bereich."""
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
    add_baseline_soc_traces(fig, df, history_slot_count=3)
    bl_traces = [trace for trace in fig.data if trace.name == "SoC BL Ziel"]
    assert len(bl_traces) == 1
    first_x = _trace_x_vienna(bl_traces[0].x[0])
    assert first_x == _dt(2026, 6, 15, 14, 45)
    assert first_x == slots[3]


def test_baseline_soc_bridges_extrapolation_start():
    """Keine Lücke am Übergang neutral→grün (Preis extrapoliert) für SoC BL Ziel."""
    slots = [_dt(2026, 7, 5, hour, 0) for hour in (20, 21, 22, 23)]
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Simulierter SoC (%)": [60.0, 59.0, 58.0, 57.0],
        "Geplante Batterie-Aktion (kW)": [0.0] * 4,
        "Preis extrapoliert": [False, False, True, True],
    })
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_baseline_soc_traces(fig, df, extrap_start=2, extrap_end=4)
    bl_traces = [trace for trace in fig.data if trace.name == "SoC BL Ziel"]
    assert len(bl_traces) == 2
    assert bl_traces[0].y[-1] == 59.0
    assert bl_traces[1].y[0] == 59.0
    assert bl_traces[1].y[1] == 58.0
    assert _trace_x_vienna(bl_traces[1].x[0]) == _dt(2026, 7, 5, 21, 0)
    assert _trace_x_vienna(bl_traces[1].x[1]) == _dt(2026, 7, 5, 22, 0)


def test_price_trace_bridges_extrapolation_start():
    """Keine x-Lücke an Zonengrenzen — HV-Schritt bleibt durchgängig."""
    slots = [_dt(2026, 7, 5, hour, 0) for hour in (20, 21, 22, 23)]
    rows = []
    for index, slot in enumerate(slots):
        rows.append({
            "slot_datetime": slot,
            "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
            "Simulierter SoC (%)": 50.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Strompreis (Cent/kWh)": 20.0 + index * 5,
            "Preis extrapoliert": index >= 2,
        })
    df = pd.DataFrame(rows)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_price_on_soc_axis_trace(fig, df, axis, extrap_start=2, extrap_end=4)
    price_trace = next(trace for trace in fig.data if trace.name == "Preis")
    boundary_x = _dt(2026, 7, 5, 22, 0)
    boundary_points = [
        (float(y), _trace_x_vienna(x))
        for x, y in zip(price_trace.x, price_trace.y)
        if _trace_x_vienna(x) == boundary_x
    ]
    assert len(boundary_points) >= 2
    ys = {y for y, _x in boundary_points}
    assert len(ys) == 2
    assert 25.0 in ys
    assert 30.0 in ys


def test_soc_trace_bridges_extrapolation_start():
    """Keine Lücke am Übergang neutral→grün (Preis extrapoliert)."""
    slots = [_dt(2026, 7, 5, hour, 0) for hour in (20, 21, 22, 23)]
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Simulierter SoC (%)": [60.0, 59.0, 58.0, 57.0],
        "Geplante Batterie-Aktion (kW)": [0.0] * 4,
        "Preis extrapoliert": [False, False, True, True],
    })
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_optimized_soc_trace(fig, df, axis, extrap_start=2, extrap_end=4)
    soc_traces = [trace for trace in fig.data if trace.name == "SoC"]
    assert len(soc_traces) == 2
    assert soc_traces[0].y[-1] == 59.0
    assert soc_traces[1].y[0] == 59.0
    assert soc_traces[1].y[1] == 58.0
    assert _trace_x_vienna(soc_traces[1].x[0]) == _dt(2026, 7, 5, 21, 0)
    assert _trace_x_vienna(soc_traces[1].x[1]) == _dt(2026, 7, 5, 22, 0)


def _forecast_zone_vrect(fig) -> object | None:
    from ui.chart_colors import CHART_ZONE_FORECAST_FILL

    for shape in fig.layout.shapes or []:
        if shape.fillcolor == CHART_ZONE_FORECAST_FILL:
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
    green = _forecast_zone_vrect(fig)
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
    green = _forecast_zone_vrect(fig)
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
    green = _forecast_zone_vrect(fig)
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
    green = _forecast_zone_vrect(fig)
    assert green is not None
    assert green.x0 == axis.legacy_index_time(idx - 0.5)
    assert green.x1 == x_right


def test_chart2_s2_split_mode_shows_cost_summary_annotations(monkeypatch):
    """Backlog: Einsparungs-Text auch in SA₀→SA₁ und SA₁→SA₂ (Gesamt-Horizont)."""
    captured: dict = {}

    def _capture_chart(fig, **_kwargs):
        captured["fig"] = fig

    monkeypatch.setattr("ui.charts.st.plotly_chart", _capture_chart)
    monkeypatch.setattr("ui.charts.render_title_with_help", lambda *_a, **_k: None)

    slots = [_dt(2026, 6, 15, hour, 0) for hour in range(8, 14)]
    slot_count = len(slots)
    history_slot_count = 3
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Preis extrapoliert": [False] * slot_count,
    })
    render_cumulative_cost_chart(
        df,
        hourly_matched_baseline_cost_euro=[0.1] * slot_count,
        hourly_optimized_cost_euro=[0.08] * slot_count,
        hourly_matched_baseline_consumption_kwh=[0.5] * slot_count,
        hourly_optimized_consumption_kwh=[0.45] * slot_count,
        matched_baseline_cost_euro=12.34,
        optimized_cost_euro=11.50,
        history_slot_count=history_slot_count,
        slot_actual_cost_euro=[0.05] * history_slot_count,
        slot_actual_consumption_kwh=[0.2] * history_slot_count,
    )
    texts = [
        getattr(item, "text", "")
        for item in (captured["fig"].layout.annotations or [])
    ]
    assert any("BL Ziel: 12.34" in text for text in texts)
    assert any("Optimiert: 11.50" in text for text in texts)
    assert any(text.startswith("Ersparnis:") for text in texts)


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
