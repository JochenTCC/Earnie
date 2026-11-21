"""Tests für Einsparungs-Snapshots."""
from __future__ import annotations

from optimizer.simulation import build_savings_snapshot


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
