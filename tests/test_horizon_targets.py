"""Tests für Planungshorizont-Ziele (Jetzt→SA₂, nicht nur 24 h)."""
from __future__ import annotations

from optimizer.targets import (
    build_baseline_targets_detail,
    resolve_baseload_kwh,
)
from data.consumer_targets import resolve_horizon_flex_targets_kwh


def _extended_matrix(hours: int = 36) -> list[dict]:
    return [
        {
            "hour": h,
            "expected_p_act": 1.0,
            "expected_flex_kw": {"swimspa": 0.5, "eauto": 0.0, "waermepumpe": 0.0},
        }
        for h in range(hours)
    ]


def test_resolve_baseload_kwh_sums_full_matrix():
    matrix = _extended_matrix(36)
    assert resolve_baseload_kwh(matrix) == 36.0


def test_baseline_flex_profile_sums_full_matrix():
    matrix = _extended_matrix(30)
    details = build_baseline_targets_detail(matrix)
    swimspa = next(row for row in details if row["id"] == "swimspa")
    assert swimspa["target_kwh"] == 15.0


def test_horizon_flex_targets_sums_full_matrix():
    matrix = _extended_matrix(40)
    totals = resolve_horizon_flex_targets_kwh(matrix)
    assert totals["swimspa"] == 20.0
