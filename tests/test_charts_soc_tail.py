"""Tests für SoC-Hochrechnung am Ende des Chart-Horizonts."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from ui.chart_colors import COLOR_COST_SAVINGS, CONSUMER_PALETTE, consumer_palette_color
from ui.charts import (
    ChartSlotAxis,
    _battery_bar_times,
    _chart_has_pv_follow_bars,
    _consumer_bar_marker,
    _consumer_bar_pattern_shapes,
    _cost_summary_annotations,
    _extended_line_xy,
    _hv_line_endpoint_time,
    _segment_connected_line_xy,
    _segment_linear_connected_line_xy,
    _soc_at_chart_now,
    _soc_from_history_extrapolation,
    _soc_tail_y_from_row,
    add_baseline_soc_traces,
    add_optimized_soc_trace,
)

_TZ = ZoneInfo("Europe/Vienna")


def _hourly_axis(length: int, start: datetime | None = None) -> ChartSlotAxis:
    t0 = start or datetime(2025, 6, 17, 0, 0, tzinfo=_TZ)
    slots = [t0 + timedelta(hours=index) for index in range(length)]
    return ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))


def test_consumer_bar_marker_pattern_has_visible_contrast():
    marker = _consumer_bar_marker("#00bcd4", ["", "/"], 0.65)
    pattern = marker["pattern"]
    assert pattern["fgcolor"] != pattern["bgcolor"]
    assert pattern["fillmode"] == "overlay"


def test_consumer_bar_pattern_shapes_pv_follow_only_when_active():
    segment = pd.DataFrame({
        "E-Auto (kW)": [0.0, 2.0, 3.5],
        "E-Auto pv_follow": [1, 1, 0],
    })
    shapes = _consumer_bar_pattern_shapes(segment, "E-Auto (kW)", "E-Auto pv_follow")
    assert shapes == ["", "/", ""]


def test_consumer_bar_pattern_shapes_immediate_charge_uses_karo():
    segment = pd.DataFrame({
        "E-Auto (kW)": [3.5, 3.5, 0.0],
        "E-Auto pv_follow": [1, 0, 0],
        "E-Auto sofort_laden": [1, 1, 0],
    })
    shapes = _consumer_bar_pattern_shapes(
        segment,
        "E-Auto (kW)",
        "E-Auto pv_follow",
        "E-Auto sofort_laden",
    )
    assert shapes == ["+", "+", ""]


def test_chart_has_immediate_charge_bars():
    from ui.charts import _chart_has_immediate_charge_bars

    df = pd.DataFrame({
        "E-Auto (kW)": [3.5, 0.0],
        "E-Auto sofort_laden": [1, 0],
    })
    assert _chart_has_immediate_charge_bars(df) is True


def test_chart_has_pv_follow_bars():
    df = pd.DataFrame({
        "E-Auto (kW)": [0.0, 2.0],
        "E-Auto pv_follow": [0, 1],
        "SwimSpa (kW)": [0.0, 0.0],
    })
    assert _chart_has_pv_follow_bars(df) is True


def test_soc_tail_y_reflects_battery_action():
    row = pd.Series({
        "Simulierter SoC (%)": 60.0,
        "Geplante Batterie-Aktion (kW)": 2.0,
    })
    tail = _soc_tail_y_from_row(row)
    assert tail is not None
    assert tail > 60.0


def test_soc_tail_y_returns_none_for_missing_soc():
    row = pd.Series({
        "Simulierter SoC (%)": None,
        "Geplante Batterie-Aktion (kW)": 2.0,
    })
    assert _soc_tail_y_from_row(row) is None


def test_consumer_palette_spans_blue_violet_to_yellow_orange():
    assert len(CONSUMER_PALETTE) == 8
    assert consumer_palette_color(0) == CONSUMER_PALETTE[0]
    assert consumer_palette_color(7) == CONSUMER_PALETTE[-1]
    assert CONSUMER_PALETTE[0] != CONSUMER_PALETTE[-1]


def test_grid_line_x_centered_on_hour_slots():
    axis = _hourly_axis(4)
    values = pd.Series([1.0, 2.0, 3.0, 4.0])
    line_x, _ = _segment_connected_line_xy(
        axis,
        values,
        0,
        4,
        step_line=True,
        anchor_fraction=0.5,
    )
    expected = axis.at(slice(None), 0.5).tolist() + [_hv_line_endpoint_time(axis)]
    assert line_x.dt.floor("s").tolist() == pd.Series(expected).dt.floor("s").tolist()


def test_segment_connected_line_bridges_interior_boundary_for_hv():
    axis = _hourly_axis(4)
    values = pd.Series([10.0, 20.0, 30.0, 40.0])
    line_x, line_y = _segment_connected_line_xy(axis, values, 2, 4, step_line=True)
    assert line_x.iloc[0] == axis.at(2, 0.0).iloc[0]
    assert line_y.iloc[0] == 20.0
    assert line_y.iloc[1] == 30.0


def test_segment_linear_connection_is_continuous_across_boundary():
    axis = _hourly_axis(4)
    values = pd.Series([10.0, 20.0, 30.0, 40.0])
    x_before, y_before = _segment_linear_connected_line_xy(axis, values, 0, 2)
    x_after, y_after = _segment_linear_connected_line_xy(axis, values, 2, 4)
    assert x_before.iloc[-1] == x_after.iloc[0]
    assert y_before.iloc[-1] == y_after.iloc[0]
    assert y_after.iloc[1] == 30.0


def test_segment_linear_matches_unsegmented_line():
    axis = _hourly_axis(4)
    values = pd.Series([10.0, 20.0, 30.0, 40.0])
    full_x, full_y = _segment_linear_connected_line_xy(axis, values, 0, 4)
    x_before, y_before = _segment_linear_connected_line_xy(axis, values, 0, 2)
    x_after, y_after = _segment_linear_connected_line_xy(axis, values, 2, 4)
    merged_x = pd.concat([x_before, x_after.iloc[1:]], ignore_index=True)
    merged_y = pd.concat([y_before, y_after.iloc[1:]], ignore_index=True)
    pd.testing.assert_series_equal(
        merged_x.dt.floor("s"),
        full_x.dt.floor("s"),
    )
    pd.testing.assert_series_equal(merged_y, full_y)


def test_segment_connected_line_first_segment_unchanged():
    axis = _hourly_axis(3)
    values = pd.Series([10.0, 20.0, 30.0])
    line_x, line_y = _segment_linear_connected_line_xy(axis, values, 0, 2)
    assert line_y.iloc[0] == 10.0
    assert line_y.iloc[-1] == 20.0
    assert line_x.iloc[-1] == axis.at(1, 0.0).iloc[0]


def test_extended_soc_line_uses_tail_not_flat_repeat():
    axis = _hourly_axis(2)
    y = pd.Series([50.0, 55.0])
    _, extended_y = _extended_line_xy(axis, y, tail_y=62.0)
    assert extended_y.iloc[-1] == 62.0
    assert extended_y.iloc[-2] == 55.0


def test_hv_line_endpoint_time_matches_last_slot():
    axis24 = _hourly_axis(24)
    assert _hv_line_endpoint_time(axis24) == axis24.legacy_index_time(23.5)
    axis1 = _hourly_axis(1)
    assert _hv_line_endpoint_time(axis1) == axis1.legacy_index_time(0.5)


def test_soc_intra_hour_ramp_replaces_flat_milp_tail():
    """Keine horizontale SoC-Treppe zwischen Jetzt und Stundenende."""
    import plotly.graph_objects as go

    now = datetime(2026, 6, 15, 14, 37, tzinfo=_TZ)
    hour_end = datetime(2026, 6, 15, 15, 0, tzinfo=_TZ)
    slots = [
        datetime(2026, 6, 15, 14, 0, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 15, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 30, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 45, tzinfo=_TZ),
        hour_end,
    ]
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Simulierter SoC (%)": [40.0, 41.0, 42.0, 60.0, 61.0],
        "Geplante Batterie-Aktion (kW)": [0.0, 0.0, 0.0, 2.0, 0.0],
    })
    milp_row = pd.Series({
        "Simulierter SoC (%)": 60.0,
        "Geplante Batterie-Aktion (kW)": 2.0,
    })
    tail_y = _soc_tail_y_from_row(milp_row)
    assert tail_y is not None
    assert tail_y > 60.0

    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_optimized_soc_trace(
        fig, df, axis, history_slot_count=3, chart_now=now,
    )
    milp_trace = [trace for trace in fig.data if trace.name == "SoC"][-1]
    xs = [pd.Timestamp(x).to_pydatetime().replace(tzinfo=_TZ) for x in milp_trace.x]
    ys = {
        pd.Timestamp(x).to_pydatetime().replace(tzinfo=_TZ): float(y)
        for x, y in zip(milp_trace.x, milp_trace.y)
    }

    assert datetime(2026, 6, 15, 14, 45, tzinfo=_TZ) not in xs
    assert now in xs
    assert hour_end in xs
    assert ys[hour_end] == tail_y
    assert ys[hour_end] > 60.0


def test_soc_intra_hour_ramp_before_now_replaces_flat_milp_head():
    """Keine horizontale SoC-Treppe zwischen erstem MILP-Viertel und Jetzt."""
    import plotly.graph_objects as go

    now = datetime(2026, 6, 15, 14, 37, tzinfo=_TZ)
    hour_end = datetime(2026, 6, 15, 15, 0, tzinfo=_TZ)
    slots = [
        datetime(2026, 6, 15, 14, 0, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 15, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 30, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 45, tzinfo=_TZ),
        hour_end,
    ]
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Simulierter SoC (%)": [40.0, 41.0, 60.0, 60.0, 60.0],
        "Geplante Batterie-Aktion (kW)": [0.0, 2.0, 0.0, 0.0, 0.0],
        "Preis extrapoliert": [False] * 5,
    })
    axis = ChartSlotAxis.from_dataframe(df)
    history_slot_count = 2
    y_at_now = _soc_from_history_extrapolation(
        axis, df["Simulierter SoC (%)"], df, now, history_slot_count,
    )
    assert y_at_now > 41.0
    assert y_at_now < 60.0

    fig = go.Figure()
    add_optimized_soc_trace(
        fig, df, axis, history_slot_count=history_slot_count, chart_now=now,
    )
    milp_trace = [trace for trace in fig.data if trace.name == "SoC"][-1]
    ys = {
        pd.Timestamp(x).to_pydatetime().replace(tzinfo=_TZ): float(y)
        for x, y in zip(milp_trace.x, milp_trace.y)
    }
    first_milp = datetime(2026, 6, 15, 14, 30, tzinfo=_TZ)
    assert ys[first_milp] < 60.0
    assert ys[now] == pytest.approx(y_at_now)
    assert ys[now] < 60.0


def test_baseline_soc_meets_optimized_soc_at_now():
    """BL-Ziel und optimierter SoC treffen sich am Jetzt-Marker."""
    import plotly.graph_objects as go

    now = datetime(2026, 6, 15, 14, 37, tzinfo=_TZ)
    hour_end = datetime(2026, 6, 15, 15, 0, tzinfo=_TZ)
    slots = [
        datetime(2026, 6, 15, 14, 0, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 15, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 30, tzinfo=_TZ),
        datetime(2026, 6, 15, 14, 45, tzinfo=_TZ),
        hour_end,
    ]
    optimized_df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Simulierter SoC (%)": [40.0, 41.0, 60.0, 60.0, 60.0],
        "Geplante Batterie-Aktion (kW)": [0.0, 2.0, 0.0, 0.0, 0.0],
        "Preis extrapoliert": [False] * 5,
    })
    baseline_df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Simulierter SoC (%)": [55.0, 55.0, 70.0, 70.0, 70.0],
        "Geplante Batterie-Aktion (kW)": [0.0] * 5,
        "Preis extrapoliert": [False] * 5,
    })
    axis = ChartSlotAxis.from_dataframe(optimized_df)
    history_slot_count = 2
    fig = go.Figure()
    add_optimized_soc_trace(
        fig, optimized_df, axis,
        history_slot_count=history_slot_count, chart_now=now,
    )
    add_baseline_soc_traces(
        fig,
        baseline_df,
        history_slot_count=history_slot_count,
        chart_now=now,
        soc_at_now=_soc_at_chart_now(
            axis, optimized_df, now, history_slot_count,
        ),
    )
    soc_trace = [trace for trace in fig.data if trace.name == "SoC"][-1]
    bl_trace = next(trace for trace in fig.data if trace.name == "SoC BL Ziel")
    soc_at_now = {
        pd.Timestamp(x).to_pydatetime().replace(tzinfo=_TZ): float(y)
        for x, y in zip(soc_trace.x, soc_trace.y)
    }
    bl_at_now = {
        pd.Timestamp(x).to_pydatetime().replace(tzinfo=_TZ): float(y)
        for x, y in zip(bl_trace.x, bl_trace.y)
    }
    assert now in soc_at_now
    assert now in bl_at_now
    assert bl_at_now[now] == pytest.approx(soc_at_now[now])


def test_battery_bar_times_nudged_past_slot_center():
    axis = _hourly_axis(1)
    bar_x = _battery_bar_times(axis, slice(None)).iloc[0]
    center = axis.at(0, 0.5).iloc[0]
    nudged = axis.at(0, 0.5 + 0.05).iloc[0]
    assert bar_x == nudged
    assert bar_x > center


def test_cost_summary_annotations_include_totals_and_savings_sign():
    annotations = _cost_summary_annotations(12.34, 11.50)
    assert len(annotations) == 3
    assert annotations[0]["text"] == "BL Ziel: 12.34 €"
    assert annotations[1]["text"] == "Optimiert: 11.50 €"
    assert annotations[2]["text"] == "Ersparnis: -0.84 €"
    assert annotations[2]["font"]["color"] == COLOR_COST_SAVINGS
    assert annotations[0]["xref"] == "paper"
    assert annotations[0]["xanchor"] == "left"
    assert annotations[0]["yanchor"] == "top"
    assert annotations[0]["yref"] == "y domain"
    assert annotations[0]["y"] == 1.0
    assert annotations[1]["yshift"] == -20
    assert annotations[2]["yshift"] == -40
    assert annotations[0]["font"]["size"] == 14
