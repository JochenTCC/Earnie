"""Tests für SoC-Hochrechnung am Ende des Chart-Horizonts."""
from __future__ import annotations

import pandas as pd

from ui.charts import (
    _consumer_bar_palette,
    _extended_line_xy,
    _segment_connected_line_xy,
    _segment_linear_connected_line_xy,
    _soc_tail_y_from_row,
)


def test_soc_tail_y_reflects_battery_action():
    row = pd.Series({
        "Simulierter SoC (%)": 60.0,
        "Geplante Batterie-Aktion (kW)": 2.0,
    })
    tail = _soc_tail_y_from_row(row)
    assert tail is not None
    assert tail > 60.0


def test_consumer_palette_spans_gray_to_cyan():
    colors = _consumer_bar_palette(3)
    assert len(colors) == 3
    assert colors[0] == "#7f8c8d"
    assert colors[-1] == "#00bcd4"
    assert colors[0] != colors[-1]


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
