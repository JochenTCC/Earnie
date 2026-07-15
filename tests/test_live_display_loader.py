"""Tests für runtime_store.live_display_loader."""
from __future__ import annotations

from datetime import datetime, timedelta

from optimizer import schedule as optimization_schedule
from runtime_store import live_optimization_debug
from runtime_store.live_display_loader import (
    is_persisted_display_fresh,
    load_live_display_snapshot,
    planning_matrix_from_snapshot,
    savings_info_from_snapshot,
    snapshot_age_seconds,
    snapshot_completed_at,
)


def test_snapshot_age_and_freshness():
    now = datetime(2026, 7, 5, 10, 0, 0)
    completed = (now - timedelta(minutes=59)).isoformat(timespec="seconds")
    assert snapshot_age_seconds(completed, now) == 59 * 60
    assert is_persisted_display_fresh(completed, now)
    stale = (now - timedelta(minutes=61)).isoformat(timespec="seconds")
    assert not is_persisted_display_fresh(stale, now)


def test_snapshot_completed_at_prefers_completed_at():
    snapshot = {"completed_at": "2026-07-05T10:00:00", "main_run_completed_at": "2026-07-05T09:00:00"}
    assert snapshot_completed_at(snapshot) == "2026-07-05T10:00:00"


def test_savings_info_from_snapshot():
    snapshot = {
        "savings": {
            "baseline_cost_euro": 1.0,
            "optimized_cost_euro": 0.8,
            "savings_euro": 0.2,
        },
        "simulation_rows": [{"hour": 10, "Netzbezug (kWh)": 1.0}],
        "baseline_rows": [{"hour": 10}],
        "matched_baseline_rows": [],
        "applied_targets": [],
        "energy_comparison": [],
    }
    info = savings_info_from_snapshot(snapshot)
    assert info["optimized_cost_euro"] == 0.8
    assert len(info["optimized_rows"]) == 1


def test_planning_matrix_from_snapshot():
    snapshot = {"planning_matrix": [{"slot_datetime": "2026-07-05T10:00:00", "k_act": 10.0}]}
    matrix = planning_matrix_from_snapshot(snapshot)
    assert len(matrix) == 1
    assert matrix[0]["k_act"] == 10.0
    from datetime import datetime

    assert isinstance(matrix[0]["slot_datetime"], datetime)


def test_load_live_display_snapshot_missing_returns_none(tmp_path, monkeypatch):
    missing = str(tmp_path / "missing.json")
    monkeypatch.setattr(
        live_optimization_debug,
        "_candidate_paths",
        lambda kind: [missing] if kind == "live" else [missing],
    )
    assert load_live_display_snapshot() is None


def test_freshness_constant_matches_schedule():
    from runtime_store.live_display_loader import PERSISTED_DISPLAY_MAX_AGE_SECONDS

    assert PERSISTED_DISPLAY_MAX_AGE_SECONDS == optimization_schedule.PERSISTED_DISPLAY_MAX_AGE_SECONDS
