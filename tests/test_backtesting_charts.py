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


def test_scenario_monthly_cost_chart_respects_scenario_order():
    monthly = {
        "2025-01": {
            "Live": 70.0,
            "Referenz (Live) — ohne Optimierung": 90.0,
            "Historisch (ohne Optimierung)": 100.0,
        },
    }
    order = [
        "Historisch (ohne Optimierung)",
        "Referenz (Live) — ohne Optimierung",
        "Live",
    ]
    fig = scenario_monthly_cost_chart(monthly, scenario_order=order)
    assert [trace.name for trace in fig.data] == order
