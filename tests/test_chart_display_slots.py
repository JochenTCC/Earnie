"""Tests für gemischte Chart-Display-Slots (S-2 Phase 2)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from runtime_store.history_timeline import SLOT_MISSING, SLOT_PRESENT
from ui.chart_context import (
    align_hourly_increments_to_display_slots,
    align_rows_to_display_slots,
)
from ui.charts import _mask_missing_log_slots

TZ = "Europe/Vienna"


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 15, hour, minute, tzinfo=ZoneInfo(TZ))


def test_align_rows_to_display_slots_splits_hour_into_quarters():
    hour_row = {
        "slot_datetime": _dt(14, 0),
        "Uhrzeit": "14:00",
        "Simulierter SoC (%)": 55.0,
    }
    slots = (_dt(14, 0), _dt(14, 15), _dt(14, 30), _dt(14, 45))
    rows = align_rows_to_display_slots([hour_row], slots)
    assert len(rows) == 4
    assert all(row["Simulierter SoC (%)"] == 55.0 for row in rows)
    assert [row["slot_datetime"] for row in rows] == list(slots)


def test_align_hourly_increments_splits_hour_evenly():
    from data.planning_window import compute_ui_chart_window

    LAT, LON = 47.404, 9.743
    now = _dt(14, 30)
    chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0)
    matrix = [{"slot_datetime": _dt(14, 0)}, {"slot_datetime": _dt(15, 0)}]
    slots = (_dt(14, 0), _dt(14, 15), _dt(14, 30), _dt(14, 45), _dt(15, 0))
    increments = align_hourly_increments_to_display_slots(
        [4.0, 8.0], matrix, chart, slots
    )
    assert increments == [1.0, 1.0, 1.0, 1.0, 8.0]


def test_mask_missing_log_slots_sets_nan():
    df = pd.DataFrame(
        {
            "slot_datetime": [_dt(10, 0), _dt(10, 15)],
            "Simulierter SoC (%)": [40.0, 41.0],
            "Verbrauch-Prognose (kW)": [1.0, 1.1],
            "Steuerbefehl": ["Automatik", "Automatik"],
        }
    )
    masked = _mask_missing_log_slots(df, (SLOT_MISSING, SLOT_PRESENT))
    assert pd.isna(masked.iloc[0]["Simulierter SoC (%)"])
    assert masked.iloc[1]["Simulierter SoC (%)"] == 41.0
