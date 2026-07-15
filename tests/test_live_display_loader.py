"""Tests für runtime_store.live_display_loader."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

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
from ui.simulation_results import build_optimization_display_bundle_from_snapshot


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


def test_planning_matrix_falls_back_to_simulation_rows():
    snapshot = {
        "simulation_rows": [
            {"slot_datetime": "2026-07-05T10:00:00", "Netzbezug (kW)": 1.0},
            {"slot_datetime": "2026-07-05T11:00:00", "Netzbezug (kW)": 0.5},
        ]
    }
    matrix = planning_matrix_from_snapshot(snapshot)
    assert len(matrix) == 2


def test_savings_info_from_snapshot_recomputes_hourly_series():
    snapshot = {
        "savings": {
            "baseline_cost_euro": 1.0,
            "optimized_cost_euro": 0.8,
            "savings_euro": 0.2,
        },
        "simulation_rows": [
            {
                "slot_datetime": "2026-07-05T10:00:00",
                "Netzbezug (kW)": 1.0,
                "Verbrauch-Prognose (kW)": 1.0,
                "PV-Prognose (kW)": 0.0,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Strompreis (Cent/kWh)": 30.0,
                "Einspeisevergütung (Cent/kWh)": 6.0,
            }
        ],
        "matched_baseline_rows": [
            {
                "slot_datetime": "2026-07-05T10:00:00",
                "Netzbezug (kW)": 1.2,
                "Verbrauch-Prognose (kW)": 1.2,
                "PV-Prognose (kW)": 0.0,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Strompreis (Cent/kWh)": 30.0,
                "Einspeisevergütung (Cent/kWh)": 6.0,
            }
        ],
        "baseline_rows": [{"hour": 10}],
        "applied_targets": [],
        "energy_comparison": [],
    }
    info = savings_info_from_snapshot(snapshot)
    assert info["hourly_optimized_cost_euro"] == [0.3]
    assert info["hourly_matched_baseline_cost_euro"] == [0.36]


def test_chart2_sa1_sa2_snapshot_bundle_has_nonzero_hourly_costs():
    """Regression: chart_debug_20260715_191843 — SA₁→SA₂ Chart 2 must not be all zeros."""
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "chart_debug_review"
        / "chart_debug_20260715_191843"
        / "manifest.json"
    )
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = {
        "savings": manifest["savings_summary"],
        "simulation_rows": manifest["savings_view"].get("optimized_rows", []),
        "baseline_rows": manifest.get("baseline_rows", []),
        "matched_baseline_rows": manifest.get("matched_baseline_rows", []),
        "planning_window": manifest["chart_context"]["chart_window"],
    }
    now = datetime.fromisoformat(manifest["chart_context"]["now"])
    bundle = build_optimization_display_bundle_from_snapshot(
        snapshot,
        cycle_offset=0,
        segment_index=1,
        now=now,
    )
    assert bundle is not None
    hourly = bundle.savings_view.get("hourly_optimized_cost_euro") or []
    assert sum(hourly) > 0.0
    assert sum(1 for value in hourly if value) >= 10


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
