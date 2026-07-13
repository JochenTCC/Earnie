# tests/test_backtesting_results_helpers.py
"""Tests für Backtesting-Ergebnis-Hilfsfunktionen (1.25.c)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from simulation.backtesting_log import consumption_totals_from_report
from simulation.engine import HISTORICAL_REFERENCE_ID, PlausibilityReport, PlausibilityResult
from ui.backtesting_results_helpers import (
    build_annual_cost_rows,
    build_scenario_consumption_rows,
    cons_data_has_flex_energy,
    is_single_month_test_run,
    nav_bounds_from_period,
    reference_consumption_subheader,
    reference_kwh_for_period,
    format_test_run_caption,
    scenario_consumption_subheader,
)


def _sample_cons_df() -> pd.DataFrame:
    idx = pd.date_range("2025-03-01", periods=24 * 31, freq="h", name="timestamp")
    return pd.DataFrame(
        {
            "total_kw": [1.0] * len(idx),
            "baseload_kw": [0.5] * len(idx),
            "pv_kw": [0.0] * len(idx),
        },
        index=idx,
    )


def test_is_single_month_test_run_true():
    period = {"start_month": 3, "end_month": 3}
    assert is_single_month_test_run(period) is True


def test_is_single_month_test_run_false_for_full_year():
    period = {"start_month": None, "end_month": None}
    assert is_single_month_test_run(period) is False


def test_is_single_month_test_run_false_for_different_months():
    period = {"start_month": 1, "end_month": 12}
    assert is_single_month_test_run(period) is False


def test_format_test_run_caption():
    period = {"start_month": 3, "end_month": 3, "backtesting_year": 2025}
    assert format_test_run_caption(period) == "Testlauf — nur Monat 03/2025"


def test_format_test_run_caption_none_for_full_year():
    assert format_test_run_caption({"start_month": None, "end_month": None}) is None


def test_nav_bounds_from_period_includes_end_of_day():
    period = {"start": "2025-03-01", "end": "2025-03-31"}
    start, end = nav_bounds_from_period(period)
    assert start == datetime(2025, 3, 1, 0, 0, 0)
    assert end == datetime(2025, 3, 31, 23, 59, 59)


def test_nav_bounds_from_period_none_without_dates():
    assert nav_bounds_from_period({}) is None


def test_reference_kwh_for_period_march():
    period = {"start": "2025-03-01", "end": "2025-03-31"}
    kwh = reference_kwh_for_period(_sample_cons_df(), period)
    assert kwh == 744.0


def test_build_annual_cost_rows_reference_kwh_and_delta():
    meta = {
        "reference_id": HISTORICAL_REFERENCE_ID,
        "labels": {
            HISTORICAL_REFERENCE_ID: "Historisch",
            "live": "Live",
        },
        "summary": {
            "total_eur": {
                HISTORICAL_REFERENCE_ID: 1200.0,
                "live": 1000.0,
            },
        },
    }
    rows = build_annual_cost_rows(meta, ref_kwh=5000.0)
    assert len(rows) == 1
    live_row = rows[0]
    assert live_row["Szenario"] == "Live"
    assert live_row["Jahres-kWh"] == "—"
    assert live_row["Δ vs. Referenz"] == "-200.00 €"


def test_build_annual_cost_rows_uses_per_scenario_reference():
    from simulation.engine import scenario_reference_id

    ref_id = scenario_reference_id("fixed_full")
    meta = {
        "reference_id": HISTORICAL_REFERENCE_ID,
        "reference_by_scenario": {
            "live": HISTORICAL_REFERENCE_ID,
            "fixed_full": ref_id,
        },
        "labels": {
            HISTORICAL_REFERENCE_ID: "Historisch",
            ref_id: "Referenz (Fixed)",
            "fixed_full": "Fixed Full",
        },
        "summary": {
            "total_eur": {
                HISTORICAL_REFERENCE_ID: 1200.0,
                ref_id: 1100.0,
                "fixed_full": 1050.0,
            },
        },
    }
    rows = build_annual_cost_rows(meta, ref_kwh=None)
    fixed_row = next(r for r in rows if r["Szenario"] == "Fixed Full")
    assert fixed_row["Δ vs. Referenz"] == "-50.00 €"


def test_reference_consumption_subheader_test_run():
    period = {"start_month": 3, "end_month": 3, "backtesting_year": 2025}
    assert reference_consumption_subheader(period) == (
        "Referenz-Verbrauch (Testmonat 03/2025, nicht optimiert)"
    )


def test_reference_consumption_subheader_full_year():
    assert reference_consumption_subheader({}) == "Referenz-Jahresverbrauch (nicht optimiert)"


def test_cons_data_has_flex_energy_false_without_consumer_columns(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_results_helpers.config.get_flexible_consumers",
        lambda: [{"id": "eauto"}],
    )
    df = _sample_cons_df()
    assert cons_data_has_flex_energy(df) is False


def test_cons_data_has_flex_energy_true_with_consumer_data(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_results_helpers.config.get_flexible_consumers",
        lambda: [{"id": "eauto"}],
    )
    df = _sample_cons_df()
    df["eauto_kw"] = 0.5
    assert cons_data_has_flex_energy(df) is True


def test_consumption_totals_from_report_sums_windows():
    report = PlausibilityReport()
    report.add(
        PlausibilityResult(
            window_end=datetime(2025, 1, 1, 0, 0),
            historical_kwh=10.0,
            optimized_kwh=10.5,
            diff_kwh=0.5,
            ok=True,
            historical_baseload_kwh=6.0,
            optimized_baseload_kwh=6.0,
            historical_flex_kwh=4.0,
            optimized_flex_kwh=4.5,
            baseload_diff_kwh=0.0,
            flex_diff_kwh=0.5,
        )
    )
    report.add(
        PlausibilityResult(
            window_end=datetime(2025, 1, 2, 0, 0),
            historical_kwh=12.0,
            optimized_kwh=11.0,
            diff_kwh=1.0,
            ok=False,
            historical_baseload_kwh=7.0,
            optimized_baseload_kwh=7.0,
            historical_flex_kwh=5.0,
            optimized_flex_kwh=4.0,
            baseload_diff_kwh=0.0,
            flex_diff_kwh=1.0,
        )
    )
    totals = consumption_totals_from_report(report)
    assert totals["historical_kwh"] == 22.0
    assert totals["optimized_kwh"] == 21.5
    assert totals["delta_kwh"] == -0.5
    assert totals["historical_flex_kwh"] == 9.0
    assert totals["optimized_flex_kwh"] == 8.5


def test_build_scenario_consumption_rows_includes_reference_and_optimized():
    meta = {
        "reference_id": HISTORICAL_REFERENCE_ID,
        "scenario_ids": ["live"],
        "labels": {
            HISTORICAL_REFERENCE_ID: "Historisch",
            "live": "Live",
        },
        "plausibility": {
            "live": {
                "ok_count": 29,
                "total_windows": 31,
                "consumption_totals": {
                    "historical_kwh": 500.0,
                    "optimized_kwh": 520.5,
                    "delta_kwh": 20.5,
                },
            },
        },
    }
    rows = build_scenario_consumption_rows(meta, ref_kwh=500.0)
    assert len(rows) == 2
    ref_row = next(r for r in rows if r["Szenario"] == "Historisch")
    assert ref_row["Baseline Spec (kWh)"] == "500.0"
    assert ref_row["Optimiert (kWh)"] == "500.0"
    assert ref_row["Δ kWh (Opt−Baseline)"] == "+0.0"
    live_row = next(r for r in rows if r["Szenario"] == "Live")
    assert live_row["Optimiert (kWh)"] == "520.5"
    assert live_row["Δ kWh (Opt−Baseline)"] == "+20.5"
    assert live_row["Plausibilität"] == "29/31 OK"


def test_build_scenario_consumption_rows_timing_shift_note(monkeypatch):
    from ui.consumption_display.types import BaselineOptimizedOverlay

    def _fake_overlay(*_args, **_kwargs):
        return BaselineOptimizedOverlay(
            scenario_label="Live",
            consumer_ids=["pool"],
            consumer_labels={"pool": "pool"},
            baseline_kw={"pool": [2.0, 2.0, 0.0, 0.0]},
            optimized_kw={"pool": [0.0, 0.0, 2.0, 2.0]},
        )

    monkeypatch.setattr(
        "ui.backtesting_scenario_consumption.build_baseline_optimized_overlay",
        _fake_overlay,
    )
    monkeypatch.setattr(
        "ui.backtesting_scenario_consumption.detect_period_timing_shift",
        lambda *_args, **_kwargs: True,
    )
    meta = {
        "reference_id": HISTORICAL_REFERENCE_ID,
        "scenario_ids": ["live"],
        "labels": {"live": "Live"},
        "plausibility": {
            "live": {
                "ok_count": 2,
                "total_windows": 2,
                "consumption_totals": {
                    "historical_kwh": 100.0,
                    "optimized_kwh": 100.0,
                    "delta_kwh": 0.0,
                    "historical_flex_kwh": 50.0,
                    "optimized_flex_kwh": 50.0,
                },
            },
        },
    }
    rows = build_scenario_consumption_rows(
        meta,
        ref_kwh=100.0,
        hourly_df=pd.DataFrame({"consumption_kw": [1.0], "baseload_kw": [1.0]}),
        scenarios={"live": {"_house_profile": {}}},
        timestamps=["2024-01-01 00:00:00"],
    )
    live_row = next(row for row in rows if row["Szenario"] == "Live")
    assert live_row["Δ kWh (Opt−Baseline)"] == "+0.0"
    assert live_row["Δ Flex (kWh)"] == "+0.0"
    assert live_row["Hinweis"] == "Zeitverschiebung (Energie ≈ Spec)"


def test_scenario_consumption_subheader_test_run():
    period = {"start_month": 1, "end_month": 1, "backtesting_year": 2025}
    assert scenario_consumption_subheader(period) == (
        "Verbrauchsvergleich (Debug, Testmonat 01/2025)"
    )
