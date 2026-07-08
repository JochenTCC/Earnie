"""Tests für S-2 Chart 2: Ist vs. Prognose mit Brücke an der Log-Grenze."""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import pytest

from ui.charts import (
    ChartSlotAxis,
    _bridged_forecast_cumulative_series,
    _region_cumulative_series,
    _sum_slot_increments,
    add_cumulative_s2_split_traces,
)


def _mixed_slots():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Vienna")
    return [
        datetime(2026, 6, 15, 10, 0, tzinfo=tz),
        datetime(2026, 6, 15, 10, 15, tzinfo=tz),
        datetime(2026, 6, 15, 10, 30, tzinfo=tz),
        datetime(2026, 6, 15, 11, 0, tzinfo=tz),
        datetime(2026, 6, 15, 11, 15, tzinfo=tz),
        datetime(2026, 6, 15, 12, 0, tzinfo=tz),
    ]


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


def test_bridged_forecast_cumulative_continues_from_history():
    history_increments = [0.1, 0.2, 0.3]
    forecast_increments = [0.0, 0.0, 1.0, 2.0]
    bridged = _bridged_forecast_cumulative_series(
        forecast_increments,
        history_increments,
        4,
        2,
        4,
    )
    assert bridged is not None
    assert bridged.iloc[1] == pytest.approx(0.3)
    assert bridged.iloc[2] == pytest.approx(1.3)
    assert bridged.iloc[3] == pytest.approx(3.3)
    assert math.isnan(bridged.iloc[0])


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


def test_chart2_prognose_bridges_at_history_boundary():
    """Keine Lücke am Übergang grau (Log) → neutral (MILP) bei Kosten und Verbrauch."""
    slots = _mixed_slots()
    split = 3
    uhrzeit = pd.Series(slot.strftime("%d.%m. %H:%M") for slot in slots)
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))
    history_cost = [0.1, 0.2, 0.3]
    history_kwh = [0.4, 0.5, 0.6]
    n = len(slots)
    fig = go.Figure()
    add_cumulative_s2_split_traces(
        fig,
        uhrzeit,
        axis,
        history_slot_count=split,
        slot_actual_cost_euro=history_cost,
        slot_actual_consumption_kwh=history_kwh,
        hourly_matched_baseline_cost_euro=[1.0] * n,
        hourly_optimized_cost_euro=[0.8] * n,
        hourly_matched_baseline_consumption_kwh=[2.0] * n,
        hourly_optimized_consumption_kwh=[1.5] * n,
    )
    history_offset_cost = sum(history_cost)
    history_offset_kwh = sum(history_kwh)
    ist_cost = next(t for t in fig.data if t.name == "Kosten (Ist bisher)")
    forecast_cost = next(t for t in fig.data if t.name == "Kosten optimiert (Prognose)")
    ist_kwh = next(t for t in fig.data if t.name == "Verbrauch (Ist bisher)")
    forecast_kwh = next(t for t in fig.data if t.name == "Verbrauch optimiert (Prognose)")
    assert ist_cost.y[-1] == pytest.approx(history_offset_cost)
    assert forecast_cost.y[0] == pytest.approx(history_offset_cost)
    assert forecast_cost.y[1] == pytest.approx(history_offset_cost + 0.8)
    assert ist_kwh.y[-1] == pytest.approx(history_offset_kwh)
    assert forecast_kwh.y[0] == pytest.approx(history_offset_kwh)
    assert forecast_kwh.y[1] == pytest.approx(history_offset_kwh + 1.5)
