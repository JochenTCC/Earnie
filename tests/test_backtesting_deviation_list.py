"""Tests für Backtesting-Abweichungsliste (1.25.d)."""
from __future__ import annotations

from simulation.engine import HISTORICAL_REFERENCE_ID
from ui.backtesting_deviation_calendar import deviation_marker_for_case
from ui.backtesting_deviation_list import (
    _default_active_scenario,
    _resolve_chart_view,
    case_to_plausibility_failure,
    deviation_cases_for_display,
    format_deviation_delta_kwh,
    kind_label,
)
from ui.backtesting_display_bundle import VIEW_MODE_24H, VIEW_MODE_SUNRISE
from simulation.horizon_mode import SUNRISE_WINDOW


def _sample_meta() -> dict:
    return {
        "reference_id": HISTORICAL_REFERENCE_ID,
        "labels": {
            HISTORICAL_REFERENCE_ID: "Historisch",
            "live": "Live",
        },
        "critical_cases": [
            {
                "kind": "consumption_tolerance",
                "scenario_id": "live",
                "window_anchor": "2025-08-01T07:00:00",
                "historical_kwh": 32.0,
                "optimized_kwh": 34.0,
                "diff_kwh": 2.0,
            },
            {
                "kind": "strict_slow",
                "scenario_id": "live",
                "window_anchor": "2025-09-28T10:00:00",
                "slot_datetime": "2025-09-27T10:00:00",
                "simulation_hour_index": 1392,
                "strict_elapsed_sec": 3.01,
            },
            {
                "kind": "consumption_tolerance",
                "scenario_id": HISTORICAL_REFERENCE_ID,
                "window_anchor": "2025-07-01T07:00:00",
                "diff_kwh": 5.0,
            },
        ],
    }


def test_deviation_cases_for_display_excludes_reference():
    cases = deviation_cases_for_display(_sample_meta())
    scenario_ids = {c["scenario_id"] for c in cases}
    assert HISTORICAL_REFERENCE_ID not in scenario_ids
    assert len(cases) == 2


def test_deviation_cases_for_display_dedupes_same_window():
    meta = _sample_meta()
    meta["critical_cases"].append(
        {
            "kind": "strict_fallback",
            "scenario_id": "live",
            "window_anchor": "2025-08-01T07:00:00",
            "strict_elapsed_sec": 1.0,
        }
    )
    cases = deviation_cases_for_display(meta)
    same_window = [
        case
        for case in cases
        if case.get("window_anchor") == "2025-08-01T07:00:00"
    ]
    assert len(same_window) == 1
    assert same_window[0]["kind"] == "strict_fallback"


def test_deviation_cases_for_display_preserves_sort_order():
    cases = deviation_cases_for_display(_sample_meta())
    anchors = [c.get("window_anchor") or "" for c in cases]
    assert anchors == sorted(anchors)


def test_format_deviation_delta_kwh():
    plaus = {"kind": "consumption_tolerance", "diff_kwh": 1.25}
    cbc = {"kind": "strict_slow"}
    cbc_with_window = {
        "kind": "milp_no_optimal",
        "window_consumption_diff_kwh": 0.006,
    }
    assert format_deviation_delta_kwh(plaus) == "+1.25"
    assert format_deviation_delta_kwh(cbc) == "—"
    assert format_deviation_delta_kwh(cbc_with_window) == "+0.01"


def test_kind_label_known_and_unknown():
    assert kind_label("strict_fallback") == "CBC Fallback"
    assert kind_label("custom_event") == "custom_event"


def test_case_to_plausibility_failure_maps_window_anchor():
    case = {
        "window_anchor": "2025-08-01T07:00:00",
        "historical_kwh": 10.0,
        "optimized_kwh": 12.0,
        "diff_kwh": 2.0,
    }
    failure = case_to_plausibility_failure(case)
    assert failure["window_end"] == "2025-08-01T07:00:00"
    assert failure["diff_kwh"] == 2.0


def test_resolve_chart_view_from_deviation_list():
    sunrise_meta = {"period": {"horizon_mode": SUNRISE_WINDOW}}
    assert _resolve_chart_view(
        sunrise_meta,
        segment_toggle="SA₀→SA₁",
    ) == (VIEW_MODE_SUNRISE, 0)


def test_default_active_scenario_prefers_deviation():
    cases = {"live": {"kind": "strict_slow"}}
    assert _default_active_scenario(["s2-kein-pv", "live"], cases) == "live"


def test_default_active_scenario_prefers_live_without_deviation():
    assert _default_active_scenario(
        ["s2-kein-pv", "live"],
        {},
        live_scenario_id="live",
    ) == "live"


def test_default_active_scenario_falls_back_when_live_missing():
    assert _default_active_scenario(
        ["s2-kein-pv", "s3-no-battery"],
        {},
        live_scenario_id="live",
    ) == "s2-kein-pv"


def test_deviation_marker_for_case():
    assert deviation_marker_for_case(None) == ""
    assert deviation_marker_for_case({"kind": "strict_slow"}) == "🔴"
    assert (
        deviation_marker_for_case(
            {"kind": "strict_fallback", "window_consumption_ok": True}
        )
        == "🟡"
    )
