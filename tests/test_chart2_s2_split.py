"""Tests für S-2 P3a: Chart 2 Ist vs. Prognose getrennt."""
from __future__ import annotations

import math

import pytest

from ui.charts import (
    _region_cumulative_series,
    _sum_slot_increments,
)


def test_region_cumulative_series_resets_at_forecast_boundary():
    increments = [0.1, 0.2, 1.0, 2.0]
    history = _region_cumulative_series(increments, 4, 0, 2)
    forecast = _region_cumulative_series(increments, 4, 2, 4)
    assert history is not None
    assert forecast is not None
    assert history.iloc[1] == pytest.approx(0.3)
    assert math.isnan(history.iloc[2])
    assert forecast.iloc[2] == 1.0
    assert forecast.iloc[3] == 3.0
    assert math.isnan(forecast.iloc[1])


def test_region_cumulative_series_gap_in_history():
    increments = [0.1, float("nan"), 0.3]
    series = _region_cumulative_series(increments, 3, 0, 3)
    assert series is not None
    assert series.iloc[0] == 0.1
    assert math.isnan(series.iloc[1])
    assert series.iloc[2] == 0.4


def test_sum_slot_increments_skips_nan():
    increments = [0.5, float("nan"), 1.5]
    assert _sum_slot_increments(increments, 0, 3) == 2.0
