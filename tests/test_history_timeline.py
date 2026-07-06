"""Tests für 24h-Historie aus optimization_history.jsonl."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from runtime_store import history_timeline, optimization_history


NOW = datetime(2026, 6, 27, 11, 7, 30)
ANCHOR = datetime(2026, 6, 27, 11, 0, 0)


def _write_jsonl(path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def _entry(completed: datetime, **extra) -> dict:
    base = {
        "completed_at": completed.isoformat(timespec="seconds"),
        "source": "main.py",
        "success": True,
        "soc_percent": 50.0,
        "mode": 0,
        "target_power_kw": 0.0,
        "target_soc_percent": 99.0,
        "market_price_cent": 10.0,
        "forecast_pv_kw": 2.0,
        "forecast_consumption_kw": 1.0,
        "battery_plan_kw": 0.5,
        "consumer_powers_kw": {},
        "consumer_pv_follow": {},
    }
    base.update(extra)
    return base


@pytest.fixture
def history_files(tmp_path, monkeypatch):
    jsonl = tmp_path / "optimization_history.jsonl"
    legacy = tmp_path / "legacy.csv"
    monkeypatch.setattr(optimization_history, "HISTORY_FILE", str(jsonl))
    monkeypatch.setattr(optimization_history, "LEGACY_CSV_FILE", str(legacy))
    return jsonl


def test_history_window_bounds():
    start, end, anchor = history_timeline.history_window_bounds(1, NOW)
    assert anchor == ANCHOR
    assert start == datetime(2026, 6, 26, 11, 0, 0)
    assert end == ANCHOR


def test_history_window_bounds_offset_two():
    start, end, anchor = history_timeline.history_window_bounds(2, NOW)
    assert anchor == ANCHOR
    assert start == datetime(2026, 6, 25, 11, 0, 0)
    assert end == datetime(2026, 6, 26, 11, 0, 0)


def test_history_window_bounds_rejects_live_offset():
    with pytest.raises(ValueError, match="offset_days"):
        history_timeline.history_window_bounds(0, NOW)


def test_entry_to_chart_row_prefers_consumption_snapshot():
    entry = _entry(
        datetime(2026, 6, 26, 11, 0, 0),
        forecast_pv_kw=1.0,
        forecast_consumption_kw=0.5,
        consumption_snapshot={
            "baseload_kw": 0.8,
            "pv_kw": 3.5,
            "flex_kw": {"swimspa": 2.0},
            "battery_kw": -1.2,
        },
        consumer_powers_kw={"swimspa": 2.2},
    )
    row = history_timeline.entry_to_chart_row(entry, datetime(2026, 6, 26, 11, 0, 0))
    assert row["PV-Prognose (kW)"] == 3.5
    assert row["Verbrauch-Prognose (kW)"] == 0.8
    assert row[history_timeline.CHART_IST_BATTERY_KW_COLUMN] == pytest.approx(1.2)
    assert row["Uhrzeit"] == "11:00"


def test_build_timeline_present_hold_and_missing(history_files):
    window_start = datetime(2026, 6, 26, 11, 0, 0)
    entries = [
        _entry(window_start, soc_percent=40.0),
        _entry(window_start.replace(minute=30), soc_percent=45.0),
        _entry(window_start.replace(hour=12), soc_percent=55.0),
    ]
    _write_jsonl(history_files, entries)

    result = history_timeline.build_history_timeline(1, NOW)

    assert len(result.rows) == history_timeline.SLOTS_PER_DAY
    assert result.present_slot_count == 3
    assert result.missing_slot_count == 0
    assert result.held_slot_count == history_timeline.SLOTS_PER_DAY - 3
    assert result.rows[0]["Simulierter SoC (%)"] == 40.0
    assert result.rows[1]["Simulierter SoC (%)"] == 40.0
    assert result.rows[2]["Simulierter SoC (%)"] == 45.0
    assert result.rows[4]["Simulierter SoC (%)"] == 55.0


def test_build_timeline_missing_before_first_entry(history_files):
    window_start = datetime(2026, 6, 26, 11, 0, 0)
    _write_jsonl(
        history_files,
        [_entry(window_start.replace(hour=12), soc_percent=55.0)],
    )

    result = history_timeline.build_history_timeline(1, NOW)

    assert result.present_slot_count == 1
    assert result.missing_slot_count == 4
    assert result.rows[0]["Simulierter SoC (%)"] == 0.0
    assert result.rows[4]["Simulierter SoC (%)"] == 55.0


def test_build_timeline_latest_entry_wins_per_slot(history_files):
    window_start = datetime(2026, 6, 26, 11, 0, 0)
    entries = [
        _entry(window_start.replace(second=5), soc_percent=30.0),
        _entry(window_start.replace(minute=2), soc_percent=35.0),
        _entry(window_start.replace(minute=10), soc_percent=42.0),
    ]
    _write_jsonl(history_files, entries)

    result = history_timeline.build_history_timeline(1, NOW)
    assert result.present_slot_count == 1
    assert result.rows[0]["Simulierter SoC (%)"] == 42.0


def test_format_gap_notice():
    result = history_timeline.HistoryTimelineResult(
        rows=[],
        slot_costs_euro=[],
        cumulative_costs_euro=[],
        slot_consumption_kwh=[],
        cumulative_consumption_kwh=[],
        projected_savings_cumulative_euro=[],
        projected_savings_available=False,
        latest_projected_savings_euro=None,
        present_slot_count=80,
        held_slot_count=10,
        missing_slot_count=6,
        slot_qualities=(),
        window_start=ANCHOR,
        window_end=ANCHOR,
        anchor_slot=ANCHOR,
        offset_days=1,
    )
    notice = history_timeline.format_gap_notice(result)
    assert "6 von 96" in notice
    assert "10 Slots" in notice


def test_max_history_offset_days(history_files):
    earliest = datetime(2026, 6, 24, 11, 0, 0)
    _write_jsonl(history_files, [_entry(earliest)])
    assert history_timeline.max_history_offset_days(NOW) == 3


def test_load_replay_entries_between(history_files):
    inside = datetime(2026, 6, 26, 12, 0, 0)
    outside = datetime(2026, 6, 25, 10, 0, 0)
    _write_jsonl(history_files, [_entry(inside), _entry(outside)])

    start, end, _ = history_timeline.history_window_bounds(1, NOW)
    entries = optimization_history.load_replay_entries_between(start, end)
    assert len(entries) == 1
    assert entries[0]["soc_percent"] == 50.0
