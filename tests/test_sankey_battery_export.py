"""Live-Sankey: battery discharging into the grid (Live sign: battery ``+`` = discharge)."""
from __future__ import annotations

import pytest

from data.live_consumption import build_consumption_snapshot
from ui import sankey
from ui.chart_colors import (
    SANKEY_BATTERY_CHARGE_COLOR,
    SANKEY_BATTERY_DISCHARGE_COLOR,
    SANKEY_BATTERY_IDLE_COLOR,
)

_BATTERY_IDX = 2
_GRID_IDX = 1
_SYSTEM_IDX = 3
_BASELOAD_IDX = 4


@pytest.mark.parametrize(
    ("battery_kw", "expected"),
    [
        (4.98, SANKEY_BATTERY_DISCHARGE_COLOR),
        (-2.0, SANKEY_BATTERY_CHARGE_COLOR),
        (0.0, SANKEY_BATTERY_IDLE_COLOR),
    ],
)
def test_battery_color_follows_live_sign(battery_kw, expected):
    assert sankey._battery_color(battery_kw) == expected


def test_battery_export_draws_battery_to_system_to_grid(monkeypatch):
    monkeypatch.setattr(sankey, "_sankey_breakdown_consumers", lambda: [])
    data = {"pv": 0.0, "grid": -3.99, "battery": 4.98, "house": 0.99}
    snapshot = build_consumption_snapshot(data, {})

    labels, links, colors = sankey._prepare_sankey_data(
        data, 63.0, breakdown=snapshot, main_state=None
    )

    flows = {
        (src, tgt): value
        for src, tgt, value in zip(links.sources, links.targets, links.values)
    }
    assert flows == {
        (_BATTERY_IDX, _SYSTEM_IDX): pytest.approx(4.98),
        (_SYSTEM_IDX, _BASELOAD_IDX): pytest.approx(0.99),
        (_SYSTEM_IDX, _GRID_IDX): pytest.approx(3.99),
    }
    assert "Einspeisung" in labels[_GRID_IDX]
    assert "Entladen" in labels[_BATTERY_IDX]
    assert colors[_BATTERY_IDX] == SANKEY_BATTERY_DISCHARGE_COLOR
