# tests/test_backtesting_charts.py
"""Tests für Backtesting-Chart-Hilfen."""
from __future__ import annotations

from ui.backtesting_charts import scenario_monthly_cost_chart


def test_scenario_monthly_cost_chart_groups_scenarios():
    monthly = {
        "2025-01": {"Historisch": 100.0, "Runtime": 80.0},
        "2025-02": {"Historisch": 90.0, "Runtime": 70.0},
    }
    fig = scenario_monthly_cost_chart(monthly)
    assert fig.layout.barmode == "group"
    assert len(fig.data) == 2
    trace_names = {trace.name for trace in fig.data}
    assert trace_names == {"Historisch", "Runtime"}
