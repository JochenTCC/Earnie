"""Tests für SoC-Hochrechnung am Ende des Chart-Horizonts."""
from __future__ import annotations

import pandas as pd

from ui.charts import (
    _chart_has_pv_follow_bars,
    _chart_slot_x,
    _consumer_bar_marker,
    _consumer_bar_palette,
    _consumer_bar_pattern_shapes,
    _cost_summary_annotations,
    _extended_line_xy,
    _hv_line_endpoint_x,
    _segment_connected_line_xy,
    _segment_linear_connected_line_xy,
    _soc_tail_y_from_row,
)


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


def test_consumer_palette_spans_magenta_to_cyan():
    colors = _consumer_bar_palette(3)
    assert len(colors) == 3
    assert colors[0] == "#c2185b"
    assert colors[-1] == "#00bcd4"
    assert colors[0] != colors[-1]


def test_grid_line_x_centered_on_hour_slots():
    slot_x = _chart_slot_x(4)
    values = pd.Series([1.0, 2.0, 3.0, 4.0])
    line_x, _ = _segment_connected_line_xy(
        slot_x, values, 0, 4, step_line=True, x_shift=0.0
    )
    assert line_x.tolist() == [0.0, 1.0, 2.0, 3.0, 3.5]


def test_segment_connected_line_bridges_interior_boundary_for_hv():
    slot_x = pd.Series([0.0, 1.0, 2.0, 3.0])
    values = pd.Series([10.0, 20.0, 30.0, 40.0])
    line_x, line_y = _segment_connected_line_xy(slot_x, values, 2, 4, step_line=True)
    assert line_x.iloc[0] == 1.5
    assert line_y.iloc[0] == 20.0
    assert line_y.iloc[1] == 30.0


def test_segment_linear_connection_is_continuous_across_boundary():
    slot_x = pd.Series([0.0, 1.0, 2.0, 3.0])
    values = pd.Series([10.0, 20.0, 30.0, 40.0])
    x_before, y_before = _segment_linear_connected_line_xy(slot_x, values, 0, 2)
    x_after, y_after = _segment_linear_connected_line_xy(slot_x, values, 2, 4)
    assert float(x_before.iloc[-1]) == 0.5
    assert float(y_before.iloc[-1]) == 20.0
    assert float(x_after.iloc[0]) == 0.5
    assert float(y_after.iloc[0]) == 20.0
    assert float(x_after.iloc[1]) == 1.5
    assert float(y_after.iloc[1]) == 30.0


def test_segment_linear_matches_unsegmented_line():
    slot_x = pd.Series([0.0, 1.0, 2.0, 3.0])
    values = pd.Series([10.0, 20.0, 30.0, 40.0])
    full_x, full_y = _segment_linear_connected_line_xy(slot_x, values, 0, 4)
    x_before, y_before = _segment_linear_connected_line_xy(slot_x, values, 0, 2)
    x_after, y_after = _segment_linear_connected_line_xy(slot_x, values, 2, 4)
    merged_x = pd.concat([x_before, x_after.iloc[1:]], ignore_index=True)
    merged_y = pd.concat([y_before, y_after.iloc[1:]], ignore_index=True)
    pd.testing.assert_series_equal(merged_x, full_x)
    pd.testing.assert_series_equal(merged_y, full_y)


def test_segment_connected_line_first_segment_unchanged():
    slot_x = pd.Series([0.0, 1.0, 2.0])
    values = pd.Series([10.0, 20.0, 30.0])
    line_x, line_y = _segment_linear_connected_line_xy(slot_x, values, 0, 2)
    assert line_y.iloc[0] == 10.0
    assert line_y.iloc[-1] == 20.0
    assert float(line_x.iloc[-1]) == 0.5


def test_extended_soc_line_uses_tail_not_flat_repeat():
    slot_x = pd.Series([0.0, 1.0])
    y = pd.Series([50.0, 55.0])
    _, extended_y = _extended_line_xy(slot_x, y, tail_y=62.0)
    assert extended_y.iloc[-1] == 62.0
    assert extended_y.iloc[-2] == 55.0


def test_hv_line_endpoint_x_matches_last_slot():
    assert _hv_line_endpoint_x(24) == 23.5
    assert _hv_line_endpoint_x(1) == 0.5


def test_cost_summary_annotations_include_totals_and_savings_sign():
    annotations = _cost_summary_annotations(12.34, 11.50)
    assert len(annotations) == 3
    assert annotations[0]["text"] == "BL Ziel: 12.34 €"
    assert annotations[1]["text"] == "Optimiert: 11.50 €"
    assert annotations[2]["text"] == "Ersparnis: -0.84 €"
    assert annotations[2]["font"]["color"] == "#27ae60"
    assert annotations[0]["xref"] == "paper"
    assert annotations[0]["xanchor"] == "left"
    assert annotations[0]["yanchor"] == "top"
    assert annotations[0]["yref"] == "y domain"
    assert annotations[0]["y"] == 1.0
    assert annotations[1]["yshift"] == -20
    assert annotations[2]["yshift"] == -40
    assert annotations[0]["font"]["size"] == 14
