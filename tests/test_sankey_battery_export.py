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


def test_metered_consumer_without_node_stays_in_baseload(monkeypatch):
    """A metered consumer the Sankey draws no node for must not vanish from the sinks."""
    monkeypatch.setattr(
        sankey,
        "_sankey_breakdown_consumers",
        lambda: [{"id": "wp", "name": "Wärmepumpe", "chart_color_index": 0}],
    )
    data = {"pv": 0.0, "grid": 3.0, "battery": 0.0, "house": 3.0}
    snapshot = build_consumption_snapshot(data, {"wp": 1.0, "pool_known": 1.5})
    assert snapshot["baseload_kw"] == pytest.approx(0.5)

    labels, links, _colors = sankey._prepare_sankey_data(
        data, 50.0, breakdown=snapshot, main_state=None
    )

    flows = {
        (src, tgt): value
        for src, tgt, value in zip(links.sources, links.targets, links.values)
    }
    assert flows[(_SYSTEM_IDX, _BASELOAD_IDX)] == pytest.approx(2.0)
    assert flows[(_SYSTEM_IDX, _BASELOAD_IDX + 1)] == pytest.approx(1.0)
    sinks = sum(value for (src, _tgt), value in flows.items() if src == _SYSTEM_IDX)
    assert sinks == pytest.approx(3.0)
    assert "2" in labels[_BASELOAD_IDX]
