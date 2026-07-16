"""Tests für Backtesting-Abweichungs-Kalender-Index."""
from __future__ import annotations

from datetime import date, datetime

from simulation.backtesting_snapshots import normalize_window_anchor_key
from simulation.engine import CONSUMPTION_TOLERANCE_KWH, HISTORICAL_REFERENCE_ID, window_anchor_for_date
from ui.backtesting_deviation_calendar import (
    SEVERITY_NONE,
    SEVERITY_ORANGE,
    SEVERITY_RED,
    SEVERITY_YELLOW,
    anchor_for_calendar_date,
    build_deviation_calendar_index,
    case_severity,
    cases_for_date_and_scenario,
    worst_severity,
)


def _sample_meta(*, start: str = "2025-01-01", end: str = "2025-12-31") -> dict:
    return {
        "reference_id": HISTORICAL_REFERENCE_ID,
        "period": {
            "start": start,
            "end": end,
            "backtesting_year": 2025,
        },
    }


def _run_anchors_for_dates(dates: list[date]) -> list[datetime]:
    return [anchor_for_calendar_date(d) for d in dates]


def test_anchor_for_calendar_date_matches_engine():
    cell = date(2025, 8, 1)
    assert anchor_for_calendar_date(cell) == window_anchor_for_date(cell)


def test_case_severity_red_yellow_orange():
    assert case_severity({"kind": "strict_slow"}) == SEVERITY_RED
    assert case_severity({"kind": "milp_no_optimal"}) == SEVERITY_RED
    assert (
        case_severity({"kind": "strict_fallback", "window_consumption_ok": True})
        == SEVERITY_YELLOW
    )
    tol = CONSUMPTION_TOLERANCE_KWH
    assert case_severity({"kind": "consumption_tolerance", "diff_kwh": tol}) == SEVERITY_YELLOW
    assert case_severity({"kind": "consumption_tolerance", "diff_kwh": tol + 0.01}) == SEVERITY_ORANGE


def test_worst_severity_across_cases():
    cases = [
        {"kind": "consumption_tolerance", "diff_kwh": 0.1},
        {"kind": "strict_slow"},
    ]
    assert worst_severity(cases) == SEVERITY_RED


def test_worst_severity_keeps_feasible_cbc_yellow():
    cases = [
        {"kind": "consumption_tolerance", "diff_kwh": 0.1},
        {"kind": "strict_fallback", "window_consumption_ok": True},
    ]
    assert worst_severity(cases) == SEVERITY_YELLOW


def test_build_index_multi_scenario_same_day():
    day = date(2025, 8, 1)
    anchor = anchor_for_calendar_date(day)
    anchor_iso = normalize_window_anchor_key(anchor)
    meta = _sample_meta()
    cases = [
        {
            "kind": "consumption_tolerance",
            "scenario_id": "live",
            "window_anchor": anchor_iso,
            "diff_kwh": 0.2,
        },
        {
            "kind": "strict_fallback",
            "scenario_id": "s2-kein-pv",
            "window_anchor": anchor_iso,
        },
    ]
    index = build_deviation_calendar_index(
        meta,
        cases,
        run_anchors=[anchor],
    )
    cell = index[day]
    assert cell.in_run is True
    assert cell.severity == SEVERITY_RED
    assert set(cell.cases_by_scenario.keys()) == {"live", "s2-kein-pv"}


def test_build_index_marks_feasible_cbc_day_yellow():
    day = date(2025, 3, 1)
    anchor = anchor_for_calendar_date(day)
    anchor_iso = normalize_window_anchor_key(anchor)
    meta = _sample_meta(start="2025-03-01", end="2025-03-31")
    cases = [
        {
            "kind": "milp_no_optimal",
            "scenario_id": "live",
            "window_anchor": anchor_iso,
            "window_consumption_ok": True,
            "window_consumption_diff_kwh": 0.006,
        }
    ]
    index = build_deviation_calendar_index(meta, cases, run_anchors=[anchor])
    cell = index[day]
    assert cell.in_run is True
    assert cell.severity == SEVERITY_YELLOW


def test_build_index_test_month_bounds():
    meta = _sample_meta(start="2025-03-01", end="2025-03-31")
    run_anchors = _run_anchors_for_dates([date(2025, 3, 15)])
    index = build_deviation_calendar_index(meta, [], run_anchors=run_anchors)
    assert index[date(2025, 3, 15)].in_run is True
    assert index[date(2025, 3, 15)].severity == SEVERITY_NONE
    assert index[date(2025, 1, 10)].in_run is False
    assert index[date(2025, 4, 1)].in_run is False


def test_cases_for_date_and_scenario():
    day = date(2025, 9, 28)
    anchor = anchor_for_calendar_date(day)
    anchor_iso = normalize_window_anchor_key(anchor)
    meta = _sample_meta()
    case = {
        "kind": "strict_slow",
        "scenario_id": "live",
        "window_anchor": anchor_iso,
    }
    index = build_deviation_calendar_index(meta, [case], run_anchors=[anchor])
    found = cases_for_date_and_scenario(index, day, "live")
    assert found is not None
    assert found["kind"] == "strict_slow"
    assert cases_for_date_and_scenario(index, day, "missing") is None


def test_month_with_most_deviation_days():
    meta = _sample_meta()
    march_day = date(2025, 3, 5)
    april_day = date(2025, 4, 10)
    march_anchor = anchor_for_calendar_date(march_day)
    april_anchor = anchor_for_calendar_date(april_day)
    cases = [
        {
            "kind": "strict_slow",
            "scenario_id": "live",
            "window_anchor": normalize_window_anchor_key(march_anchor),
        },
        {
            "kind": "consumption_tolerance",
            "scenario_id": "live",
            "window_anchor": normalize_window_anchor_key(
                anchor_for_calendar_date(date(2025, 3, 12))
            ),
            "diff_kwh": 0.2,
        },
        {
            "kind": "strict_fallback",
            "scenario_id": "live",
            "window_anchor": normalize_window_anchor_key(april_anchor),
        },
    ]
    index = build_deviation_calendar_index(
        meta,
        cases,
        run_anchors=[
            march_anchor,
            anchor_for_calendar_date(date(2025, 3, 12)),
            april_anchor,
        ],
    )
    from ui.backtesting_deviation_calendar import month_with_most_deviation_days

    assert month_with_most_deviation_days(index, year=2025) == 3
