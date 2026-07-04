"""Tests für Simulations-Detail-Tabelle (Zeilenfarben)."""
from __future__ import annotations

import pandas as pd

from runtime_store.history_timeline import SLOT_MISSING, SLOT_PRESENT
from ui.simulation_results import _style_simulation_table


def test_style_simulation_table_colors_missing_rows_orange():
    df = pd.DataFrame(
        {
            "Uhrzeit": ["08:00", "08:15", "08:30"],
            "SoC": [None, 40.0, 45.0],
        }
    )
    qualities = (SLOT_MISSING, SLOT_PRESENT, SLOT_PRESENT)
    html = _style_simulation_table(df, qualities).to_html()
    assert "#ffe0b2" in html
    assert "#fff3e0" not in html
    assert "row0_col0" in html
