"""Tests für Live-Chart-Kontext (sunrise→sunrise)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from data.planning_window import compute_ui_chart_window
from ui.chart_context import (
    align_rows_to_chart_slots,
    align_hourly_values_to_chart_slots,
    matrix_indices_for_chart,
    savings_view_for_chart,
)

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


def test_savings_view_sums_chart_window_only():
    now = _dt(2026, 6, 15, 14, 0)
    chart = compute_ui_chart_window(now, LAT, LON, TZ)
    matrix = [
        {"slot_datetime": _dt(2026, 6, 15, hour, 0)} for hour in range(14, 20)
    ]
    savings = {
        "hourly_matched_baseline_cost_euro": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "hourly_optimized_cost_euro": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
        "hourly_savings_euro": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "hourly_matched_baseline_consumption_kwh": [1.0] * 6,
        "hourly_optimized_consumption_kwh": [1.0] * 6,
    }
    indices = matrix_indices_for_chart(matrix, chart)
    assert indices == [0, 1, 2, 3, 4, 5]
    view = savings_view_for_chart(savings, matrix, chart)
    assert view["matched_baseline_cost_euro"] == 21.0
    assert view["optimized_cost_euro"] == 18.0
    assert len(view["hourly_matched_baseline_cost_euro"]) == len(chart.slot_datetimes)


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
