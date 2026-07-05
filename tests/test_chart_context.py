"""Tests für Live-Chart-Kontext (sunrise→sunrise)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import compute_ui_chart_window
from ui.chart_context import (
    ChartDisplayContext,
    align_rows_to_chart_slots,
    align_hourly_values_to_chart_slots,
    build_display_savings_series,
    matrix_indices_for_chart,
    savings_view_for_chart,
)
from runtime_store.history_timeline import ChartHistoryResult, SLOT_PRESENT

LAT = 47.404
LON = 9.743
TZ = "Europe/Vienna"


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))


def test_align_rows_fills_missing_past_slots():
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ)
    sim_rows = [
        {
            "slot_datetime": _dt(2026, 6, 15, 14, 0),
            "Uhrzeit": "15.06. 14:00",
            "Strompreis (Cent/kWh)": 10.0,
            "Preis extrapoliert": False,
            "PV-Prognose (kW)": 1.0,
            "Verbrauch-Prognose (kW)": 0.5,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 0.0,
            "Simulierter SoC (%)": 50.0,
            "Steuerbefehl": "Automatik",
        }
    ]
    aligned = align_rows_to_chart_slots(sim_rows, chart)
    assert len(aligned) == len(chart.slot_datetimes)
    assert aligned[0]["PV-Prognose (kW)"] == 0.0
    assert any(row["PV-Prognose (kW)"] == 1.0 for row in aligned)


def test_savings_view_preserves_full_horizon_totals():
    """S-2 P3d: Kennzahlen-Summen bleiben auf vollem Horizont, nur Stundenlisten segmentiert."""
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ)
    matrix = [
        {"slot_datetime": _dt(2026, 6, 15, hour, 0)} for hour in range(14, 20)
    ]
    savings = {
        "matched_baseline_cost_euro": 99.0,
        "optimized_cost_euro": 88.0,
        "savings_matched_euro": 11.0,
        "hourly_matched_baseline_cost_euro": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "hourly_optimized_cost_euro": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
        "hourly_savings_euro": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "hourly_matched_baseline_consumption_kwh": [1.0] * 6,
        "hourly_optimized_consumption_kwh": [1.0] * 6,
    }
    view = savings_view_for_chart(savings, matrix, chart)
    assert view["matched_baseline_cost_euro"] == 99.0
    assert view["optimized_cost_euro"] == 88.0
    assert view["savings_matched_euro"] == 11.0
    assert len(view["hourly_matched_baseline_cost_euro"]) == len(chart.slot_datetimes)
    assert sum(view["hourly_matched_baseline_cost_euro"]) == 21.0


def test_max_sunrise_cycle_offset_accepts_naive_log_timestamp(monkeypatch):
    """JSONL completed_at ist oft naive lokale Zeit ohne TZ-Offset."""
    from ui.chart_context import max_sunrise_cycle_offset

    naive_earliest = datetime(2026, 6, 10, 8, 0)
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: naive_earliest,
    )
    now = _dt(2026, 6, 15, 14, 0)
    assert max_sunrise_cycle_offset(now) >= 0


def test_savings_view_aligns_hourly_to_full_chart_window():
    """Stundenkosten haben dieselbe Länge wie das Chart-Fenster (fehlende Slots = 0)."""
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ)
    matrix = [
        {"slot_datetime": _dt(2026, 6, 15, hour, 0)} for hour in range(14, 20)
    ]
    savings = {
        "hourly_matched_baseline_cost_euro": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "hourly_optimized_cost_euro": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
    }
    aligned = align_hourly_values_to_chart_slots(
        savings["hourly_matched_baseline_cost_euro"],
        matrix,
        chart,
    )
    assert len(aligned) == len(chart.slot_datetimes)
    assert sum(aligned) == 21.0
    nonzero = [value for value in aligned if value != 0.0]
    assert nonzero == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_build_display_savings_series_keeps_forecast_and_actual_separate():
    """S-2 P3a: Ist-Inkremente getrennt; MILP-Optimiert wird nicht mit Log überschrieben."""
    slots = (
        _dt(2026, 6, 15, 10, 0),
        _dt(2026, 6, 15, 10, 15),
        _dt(2026, 6, 15, 11, 0),
    )
    history = ChartHistoryResult(
        rows=[{"Uhrzeit": "15.06. 10:00"}, {"Uhrzeit": "15.06. 10:15"}],
        slot_starts=slots[:2],
        slot_qualities=(SLOT_PRESENT, SLOT_PRESENT),
        slot_costs_euro=[0.11, 0.12],
        cumulative_costs_euro=[0.11, 0.23],
        slot_consumption_kwh=[0.5, 0.6],
        cumulative_consumption_kwh=[0.5, 1.1],
        present_slot_count=2,
        held_slot_count=0,
        missing_slot_count=0,
        window_start=slots[0],
        window_end_exclusive=slots[2],
    )
    display_ctx = ChartDisplayContext(
        rows=[],
        slot_datetimes=slots,
        slot_qualities=(SLOT_PRESENT, SLOT_PRESENT, "milp"),
        history_slot_count=2,
        history_result=history,
        gap_notice=None,
        history_only=False,
    )
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ)
    matrix = [
        {"slot_datetime": _dt(2026, 6, 15, 11, 0)},
    ]
    savings_info = {
        "hourly_matched_baseline_cost_euro": [2.0],
        "hourly_optimized_cost_euro": [1.0],
        "hourly_matched_baseline_consumption_kwh": [3.0],
        "hourly_optimized_consumption_kwh": [2.0],
    }
    savings_view = savings_view_for_chart(savings_info, matrix, chart)
    view = build_display_savings_series(
        display_ctx,
        savings_view,
        matrix,
        chart,
        savings_info=savings_info,
    )
    assert view["slot_actual_cost_euro"][:2] == [0.11, 0.12]
    assert view["hourly_optimized_cost_euro"][0] != 0.11
    assert view["hourly_optimized_cost_euro"][2] == 1.0


def test_build_display_savings_series_sa1_sa2_uses_matrix_indexed_values():
    """SA₁→SA₂: Inkremente aus Matrix-Index, nicht aus chart-voralignierter Liste."""
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1)
    matrix = [
        {"slot_datetime": now.replace(minute=0) + timedelta(hours=offset)}
        for offset in range(40)
    ]
    savings_info = {
        "hourly_matched_baseline_cost_euro": [1.0] * len(matrix),
        "hourly_optimized_cost_euro": [0.5] * len(matrix),
        "hourly_matched_baseline_consumption_kwh": [2.0] * len(matrix),
        "hourly_optimized_consumption_kwh": [1.5] * len(matrix),
    }
    savings_view = savings_view_for_chart(savings_info, matrix, chart)
    display_ctx = ChartDisplayContext(
        rows=[],
        slot_datetimes=chart.slot_datetimes,
        slot_qualities=tuple("milp" for _ in chart.slot_datetimes),
        history_slot_count=0,
        history_result=None,
        gap_notice=None,
        history_only=False,
    )
    broken = build_display_savings_series(
        display_ctx, savings_view, matrix, chart
    )
    fixed = build_display_savings_series(
        display_ctx,
        savings_view,
        matrix,
        chart,
        savings_info=savings_info,
    )
    segment_sum = sum(fixed["hourly_optimized_cost_euro"])
    full_horizon_sum = sum(savings_info["hourly_optimized_cost_euro"])
    assert segment_sum < full_horizon_sum
    assert sum(broken["hourly_optimized_cost_euro"]) < segment_sum
