"""Tests für Simulations-Detail-Tabelle (Zeilenfarben)."""
from __future__ import annotations

import pandas as pd

from runtime_store.history_timeline import SLOT_MISSING, SLOT_PRESENT
from ui.simulation_results import (
    _simulation_table_column_order,
    _style_simulation_table,
)
from ui.simulation_table_view import build_frozen_simulation_table_html


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


def test_build_frozen_simulation_table_html_sticky_panes():
    df = pd.DataFrame(
        {
            "Uhrzeit": ["08:00", "08:15"],
            "SoC": [None, 40.0],
        }
    )
    qualities = (SLOT_MISSING, SLOT_PRESENT)
    html = build_frozen_simulation_table_html(_style_simulation_table(df, qualities))
    assert "sim-table-frozen-wrap" in html
    assert "position: sticky" in html
    assert "thead th:first-child" in html
    assert "#ffe0b2" in html
    assert ">Uhrzeit</th>" in html
    assert ">0</th>" not in html


def test_simulation_table_column_order_puts_flex_kw_after_uhrzeit():
    cols = _simulation_table_column_order([
        "Steuerbefehl",
        "Uhrzeit",
        "SwimSpa (kW)",
        "Datenquelle",
        "E-Auto (kW)",
        "Netzbezug (kW)",
    ])
    assert cols[:4] == ["Uhrzeit", "Datenquelle", "SwimSpa (kW)", "E-Auto (kW)"]
