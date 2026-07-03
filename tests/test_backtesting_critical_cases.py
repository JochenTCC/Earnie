"""Tests für critical_cases in backtesting_log."""
from __future__ import annotations

from datetime import datetime

from simulation.backtesting_log import (
    build_critical_cases,
    extract_critical_cases,
    summarize_critical_cases,
)
from simulation.engine import PlausibilityReport, PlausibilityResult


def test_build_critical_cases_merges_plausibility_and_cbc():
    report = PlausibilityReport()
    report.add(
        PlausibilityResult(
            window_end=datetime(2025, 8, 1, 7, 0, 0),
            historical_kwh=32.0,
            optimized_kwh=34.0,
            diff_kwh=2.0,
            ok=False,
        )
    )
    cbc = {
        "runtime_settings": [
            {
                "event": "strict_slow",
                "window_anchor": "2025-09-28T10:00:00",
                "slot_datetime": "2025-09-27T10:00:00",
                "simulation_hour_index": 1392,
                "strict_elapsed_sec": 3.01,
                "consumer_targets_kwh": {"eauto": 1.168},
            }
        ]
    }
    cases = build_critical_cases({"runtime_settings": report}, cbc)
    kinds = {c["kind"] for c in cases}
    assert kinds == {"consumption_tolerance", "strict_slow"}
    summary = summarize_critical_cases(cases)
    assert summary["total"] == 2
    assert summary["distinct_windows"] == 2


def test_extract_critical_cases_from_legacy_meta():
    meta = {
        "plausibility": {
            "runtime_settings": {
                "failures": [
                    {
                        "window_end": "2025-08-11T07:00:00",
                        "historical_kwh": 20.0,
                        "optimized_kwh": 22.0,
                        "diff_kwh": 2.0,
                    }
                ]
            }
        },
        "cbc_events_by_scenario": {
            "runtime_settings": [
                {"event": "strict_fallback", "window_anchor": "2025-09-28T10:00:00"}
            ]
        },
    }
    cases = extract_critical_cases(meta)
    assert len(cases) == 2
    assert {c["kind"] for c in cases} == {"consumption_tolerance", "strict_fallback"}
