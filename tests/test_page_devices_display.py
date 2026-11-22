"""Tests für Anzeige-Hilfen auf der Seite Manuelle Geräte."""
from __future__ import annotations

import pytest

from ui.chart_colors import COLOR_COST_SAVINGS, COLOR_COST_SAVINGS_NEGATIVE
from ui.pages.page_devices import (
    _DELTA_COLUMN,
    _appliance_loxone_power_name,
    _appliance_power_kw,
    _appliance_runtime_h,
    _delta_cell_color,
    _delta_to_best_eur,
)


@pytest.mark.parametrize(
    ("cost_eur", "best_cost_eur", "delta"),
    [
        (0.30, 0.10, 0.20),
        (0.10, 0.10, 0.0),
        (0.05, 0.10, -0.05),
    ],
)
def test_delta_to_best_eur(cost_eur: float, best_cost_eur: float, delta: float) -> None:
    assert _delta_to_best_eur(cost_eur, best_cost_eur) == pytest.approx(delta)


@pytest.mark.parametrize(
    ("delta", "expected_color"),
    [
        (0.20, f"color: {COLOR_COST_SAVINGS_NEGATIVE}"),
        (-0.20, f"color: {COLOR_COST_SAVINGS}"),
        (0.0, "color: inherit"),
    ],
)
def test_delta_cell_color(delta: float, expected_color: str) -> None:
    assert _delta_cell_color(delta) == expected_color


def test_delta_column_label_is_compact() -> None:
    assert _DELTA_COLUMN == "Delta"


def test_appliance_power_runtime_helpers() -> None:
    appliance = {
        "default_power_kw": 2.0,
        "default_runtime_h": 1.5,
        "loxone_inputs": {"power_name": "Leistung Waschmaschine"},
    }
    assert _appliance_power_kw(appliance) == pytest.approx(2.0)
    assert _appliance_runtime_h(appliance) == pytest.approx(1.5)
    assert _appliance_loxone_power_name(appliance) == "Leistung Waschmaschine"


def test_appliance_loxone_power_name_legacy_fallback() -> None:
    appliance = {"loxone_power_name": "Legacy Merker"}
    assert _appliance_loxone_power_name(appliance) == "Legacy Merker"
