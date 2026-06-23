"""Tests für SoC-Hochrechnung am Ende des Chart-Horizonts."""
from __future__ import annotations

import pandas as pd

from ui.charts import _extended_line_xy, _soc_tail_y_from_row


def test_soc_tail_y_reflects_battery_action():
    row = pd.Series({
        "Simulierter SoC (%)": 60.0,
        "Geplante Batterie-Aktion (kW)": 2.0,
    })
    tail = _soc_tail_y_from_row(row)
    assert tail is not None
    assert tail > 60.0


def test_extended_soc_line_uses_tail_not_flat_repeat():
    slot_x = pd.Series([0.0, 1.0])
    y = pd.Series([50.0, 55.0])
    _, extended_y = _extended_line_xy(slot_x, y, tail_y=62.0)
    assert extended_y.iloc[-1] == 62.0
    assert extended_y.iloc[-2] == 55.0
