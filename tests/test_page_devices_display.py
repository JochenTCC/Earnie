"""Tests für Anzeige-Hilfen auf der Seite Manuelle Geräte."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer.appliance_recommendation import recommend_start_times
from ui.chart_colors import COLOR_COST_SAVINGS, COLOR_COST_SAVINGS_NEGATIVE
from ui.pages.page_devices import (
    _DELTA_COLUMN,
    _delta_cell_color,
    _delta_to_best_eur,
    _recommendation_dataframe,
    _style_recommendation_dataframe,
)

BASE = datetime(2026, 7, 7, 18, 0)


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


def test_recommendation_dataframe_delta_to_best() -> None:
    slots = [
        {"slot_datetime": BASE + timedelta(hours=i), "k_act": price}
        for i, price in enumerate([30.0, 10.0, 20.0, 40.0, 25.0, 35.0])
    ]
    rec = recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)
    df = _recommendation_dataframe(rec)
    cheapest_row = df.loc[df["Start"] == f"{rec.cheapest.start_datetime:%H:%M}"]
    assert cheapest_row[_DELTA_COLUMN].iloc[0] == pytest.approx(0.0)
    assert df.loc[df["Start"] == f"{BASE:%H:%M}", _DELTA_COLUMN].iloc[0] == pytest.approx(
        0.20
    )


def test_style_recommendation_dataframe_formats_signed_delta() -> None:
    slots = [
        {"slot_datetime": BASE + timedelta(hours=i), "k_act": price}
        for i, price in enumerate([30.0, 10.0, 20.0, 40.0, 25.0, 35.0])
    ]
    rec = recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)
    html = _style_recommendation_dataframe(rec).to_html()
    assert "+0.20" in html
    assert "+0.00" in html
    assert COLOR_COST_SAVINGS_NEGATIVE in html
    assert COLOR_COST_SAVINGS not in html or "+0.00" in html
