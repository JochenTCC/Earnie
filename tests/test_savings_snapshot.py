"""Tests für Einsparungs-Snapshots und Historie-Aggregation."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from optimizer.simulation import build_savings_snapshot
from runtime_store import history_timeline, optimization_history


def _savings_info() -> dict:
    return {
        "baseline_cost_euro": 2.0,
        "matched_baseline_cost_euro": 1.8,
        "optimized_cost_euro": 1.2,
        "savings_euro": 0.8,
        "savings_matched_euro": 0.6,
        "hourly_savings_euro": [0.1, 0.2, 0.3],
        "hourly_matched_baseline_cost_euro": [0.5, 0.4, 0.3],
        "hourly_optimized_cost_euro": [0.4, 0.2, 0.0],
    }


def test_build_savings_snapshot_rounds_and_omits_rows():
    snapshot = build_savings_snapshot(_savings_info())
    assert snapshot["savings_matched_euro"] == 0.6
    assert snapshot["hourly_savings_euro"] == [0.1, 0.2, 0.3]
    assert "optimized_rows" not in snapshot


@pytest.fixture
def history_files(tmp_path, monkeypatch):
    jsonl = tmp_path / "optimization_history.jsonl"
    monkeypatch.setattr(optimization_history, "HISTORY_FILE", str(jsonl))
    return jsonl


def test_projected_savings_from_history_entries(history_files):
    window_start = datetime(2026, 6, 26, 11, 0, 0)
    savings = {
        "savings_matched_euro": 1.5,
        "hourly_savings_euro": [0.25, 0.25, 0.25, 0.25],
        "matched_baseline_cost_euro": 2.0,
        "optimized_cost_euro": 0.5,
        "baseline_cost_euro": 2.2,
        "savings_euro": 1.7,
        "hourly_matched_baseline_cost_euro": [0.5, 0.5, 0.5, 0.5],
        "hourly_optimized_cost_euro": [0.25, 0.25, 0.25, 0.25],
    }
    entries = [
        {
            "completed_at": window_start.isoformat(timespec="seconds"),
            "source": "main.py",
            "success": True,
            "soc_percent": 50.0,
            "mode": 0,
            "target_power_kw": 0.0,
            "target_soc_percent": 99.0,
            "market_price_cent": 10.0,
            "forecast_pv_kw": 2.0,
            "forecast_consumption_kw": 1.0,
            "battery_plan_kw": 0.5,
            "consumer_powers_kw": {},
            "current_hour": 11,
            "savings_snapshot": savings,
        },
        {
            "completed_at": window_start.replace(hour=12).isoformat(timespec="seconds"),
            "source": "main.py",
            "success": True,
            "soc_percent": 55.0,
            "mode": 0,
            "target_power_kw": 0.0,
            "target_soc_percent": 99.0,
            "market_price_cent": 8.0,
            "forecast_pv_kw": 3.0,
            "forecast_consumption_kw": 1.0,
            "battery_plan_kw": 0.0,
            "consumer_powers_kw": {},
            "current_hour": 12,
            "savings_snapshot": {
                **savings,
                "hourly_savings_euro": [0.4, 0.1, 0.0, 0.0],
                "savings_matched_euro": 2.0,
            },
        },
    ]
    with open(history_files, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")

    now = datetime(2026, 6, 27, 11, 7, 30)
    result = history_timeline.build_history_timeline(1, now)

    assert result.projected_savings_available is True
    assert result.latest_projected_savings_euro == 2.0
    assert result.projected_savings_cumulative_euro[3] == 0.25
    assert result.projected_savings_cumulative_euro[7] == 0.65
