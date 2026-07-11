"""Tests für critical_cases in backtesting_log."""
from __future__ import annotations

from datetime import datetime

from simulation.backtesting_log import (
    build_critical_cases,
    dedupe_critical_cases_by_window,
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
        "live": [
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
    cases = build_critical_cases({"live": report}, cbc)
    kinds = {c["kind"] for c in cases}
    assert kinds == {"consumption_tolerance", "strict_slow"}
    summary = summarize_critical_cases(cases)
    assert summary["total"] == 2
    assert summary["distinct_windows"] == 2


def test_extract_critical_cases_from_legacy_meta():
    meta = {
        "plausibility": {
            "live": {
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
            "live": [
                {"event": "strict_fallback", "window_anchor": "2025-09-28T10:00:00"}
            ]
        },
    }
    cases = extract_critical_cases(meta)
    assert len(cases) == 2
    assert {c["kind"] for c in cases} == {"consumption_tolerance", "strict_fallback"}


def test_dedupe_critical_cases_keeps_most_critical_per_window():
    cases = [
        {
            "kind": "consumption_tolerance",
            "scenario_id": "live",
            "window_anchor": "2025-08-01T07:00:00",
            "diff_kwh": 1.0,
        },
        {
            "kind": "strict_slow",
            "scenario_id": "live",
            "window_anchor": "2025-08-01T07:00:00",
            "strict_elapsed_sec": 2.5,
        },
        {
            "kind": "consumption_tolerance",
            "scenario_id": "fixture_5kwh",
            "window_anchor": "2025-08-01T07:00:00",
            "diff_kwh": 3.0,
        },
    ]
    deduped = dedupe_critical_cases_by_window(cases)
    assert len(deduped) == 2
    by_scenario = {case["scenario_id"]: case for case in deduped}
    assert by_scenario["live"]["kind"] == "strict_slow"
    assert by_scenario["fixture_5kwh"]["kind"] == "consumption_tolerance"


def test_dedupe_critical_cases_prefers_higher_consumption_diff():
    cases = [
        {
            "kind": "consumption_tolerance",
            "scenario_id": "live",
            "window_anchor": "2025-08-01T07:00:00",
            "diff_kwh": 1.0,
        },
        {
            "kind": "consumption_tolerance",
            "scenario_id": "live",
            "window_anchor": "2025-08-01T07:00:00",
            "diff_kwh": -4.0,
        },
    ]
    deduped = dedupe_critical_cases_by_window(cases)
    assert len(deduped) == 1
    assert deduped[0]["diff_kwh"] == -4.0
