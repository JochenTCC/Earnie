# tests/test_backtesting_plausibility_charts.py
"""Tests für Plausibilitäts-Fenster-Charts."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from ui.backtesting_plausibility_charts import (
    failure_window_label,
    plausibility_window_consumption_chart,
    slice_cons_data_for_window,
)


def test_failure_window_label_contains_delta():
    label = failure_window_label(
        {"window_end": "2025-06-15T07:00:00", "diff_kwh": 1.25}
    )
    assert "2025-06-15" in label
    assert "+1.25" in label


def test_slice_cons_data_for_window_returns_24_rows():
    window_end = datetime(2025, 6, 15, 7, 0, 0)
    start = window_end - pd.Timedelta(hours=24)
    index = pd.date_range(start, periods=24, freq="h")
    cons_df = pd.DataFrame(
        {"total_kw": [1.0] * 24, "baseload_kw": [0.5] * 24},
        index=index,
    )
    sliced = slice_cons_data_for_window(cons_df, window_end.isoformat())
    assert len(sliced) == 24
    assert sliced["total_kw"].notna().all()


def test_plausibility_window_consumption_chart_has_traces():
    failure = {
        "window_end": "2025-06-15T07:00:00",
        "historical_kwh": 10.0,
        "optimized_kwh": 12.0,
        "diff_kwh": 2.0,
    }
    index = pd.date_range("2025-06-14 07:00:00", periods=2, freq="h")
    cons_slice = pd.DataFrame(
        {"total_kw": [1.0, 2.0], "baseload_kw": [0.5, 1.0]},
        index=index,
    )
    fig = plausibility_window_consumption_chart(cons_slice, failure)
    assert len(fig.data) >= 2
