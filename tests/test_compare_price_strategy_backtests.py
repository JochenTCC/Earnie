"""Tests für Preisstrategie-Vergleichsbericht."""
from __future__ import annotations

from scripts.compare_price_strategy_backtests import build_comparison


def test_build_comparison_includes_cost_delta():
    mirror = {
        "reference_id": "historical_reference",
        "labels": {
            "historical_reference": "Ref",
            "live": "Baseline",
        },
        "summary": {
            "total_eur": {
                "historical_reference": 1000.0,
                "live": 900.0,
            }
        },
        "plausibility": {"live": {"total_windows": 10, "ok_count": 10}},
        "period": {"start": "2025-01-01", "last_ts": "2025-12-31", "price_strategy": "mirror"},
    }
    forecast = {
        "reference_id": "historical_reference",
        "labels": mirror["labels"],
        "summary": {
            "total_eur": {
                "historical_reference": 1000.0,
                "live": 880.0,
            }
        },
        "plausibility": {"live": {"total_windows": 10, "ok_count": 9}},
        "period": {"start": "2025-01-01", "last_ts": "2025-12-31", "price_strategy": "forecast"},
    }
    report = build_comparison(mirror, forecast)
    assert "900.00" in report
    assert "880.00" in report
    assert "Δ Einsparung" in report
