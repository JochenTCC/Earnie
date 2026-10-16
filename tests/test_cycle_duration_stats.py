"""Always-on cycle duration / punctuality log (EarlyStart P0)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import pytest

from runtime_store import cycle_duration_stats as stats_mod
from runtime_store.cycle_duration_stats import (
    EVENT_COLD_START,
    EVENT_WEATHER_FETCH,
    OUTCOME_ERROR,
    OUTCOME_NO_WRITES,
    OUTCOME_OK,
    CycleStats,
    cycle_stats_session,
    load_records,
    mark_writes_done,
    punctuality_summary,
    record_event,
    set_horizon_slots,
    stats_path,
)

TRIGGER_QH = "quarter_hour"
TRIGGER_OOB = "request_optimize"


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    return tmp_path


def _record(started: datetime, writes: datetime | None, *, trigger=TRIGGER_QH, woke=None, tick=None):
    stats = CycleStats(trigger=trigger, started_at=started, woke_at=woke, tick=tick)
    if writes is not None:
        stats.mark_writes_done(writes)
    return stats.to_record(
        outcome=OUTCOME_OK if writes else OUTCOME_NO_WRITES,
        finished_at=started + timedelta(seconds=250),
        version="test",
    )


def test_record_measures_delays_against_the_slot_tick():
    row = _record(
        datetime(2026, 10, 15, 9, 16, 13),
        datetime(2026, 10, 15, 9, 17, 57),
        woke=datetime(2026, 10, 15, 9, 16, 10),
    )
    assert row["tick"].startswith("2026-10-15T09:15:00")
    assert row["wake_delay_sec"] == pytest.approx(70.0)
    assert row["start_delay_sec"] == pytest.approx(73.0)
    assert row["late_by_sec"] == pytest.approx(177.0)
    assert row["duration_sec"] == pytest.approx(250.0)
    assert row["on_time"] is None


def test_writes_within_tolerance_count_as_on_time():
    tick = datetime(2026, 10, 15, 9, 15)
    row = _record(tick, datetime(2026, 10, 15, 9, 15, 1), tick=tick)
    assert row["late_by_sec"] == pytest.approx(1.0)
    assert row["on_time"] is True
    late = _record(tick, datetime(2026, 10, 15, 9, 15, 3), tick=tick)
    assert late["on_time"] is False


def test_first_cycle_after_start_is_excluded_from_punctuality():
    """A regular cycle with no planned tick stays in the log but not in rate or P95.

    NAS 2026-10-15: the restart at 12:17 (late_by_sec +213 s) alone made P95 +213 s.
    """
    started = datetime(2026, 10, 15, 12, 17)
    writes = datetime(2026, 10, 15, 12, 18, 33)
    stats = CycleStats(trigger=TRIGGER_QH, started_at=started)
    stats.note_event(EVENT_COLD_START)
    stats.mark_writes_done(writes)
    row = stats.to_record(outcome=OUTCOME_OK, finished_at=writes, version="t")
    assert row["tick"].startswith("2026-10-15T12:15:00")
    assert row["late_by_sec"] == pytest.approx(213.0)
    assert row["on_time"] is None
    now = datetime(2026, 10, 15, 13, 0)
    regular = {
        "tick": (now - timedelta(minutes=15)).isoformat(),
        "late_by_sec": 0.4,
        "on_time": True,
    }
    summary = punctuality_summary([regular, row], now=now, window=timedelta(hours=24))
    assert summary["cycles"] == 1
    assert summary["on_time"] == 1
    assert summary["p95_late_sec"] == pytest.approx(0.4)


def test_out_of_band_cycle_has_no_punctuality():
    row = _record(
        datetime(2026, 10, 15, 9, 20, 0),
        datetime(2026, 10, 15, 9, 22, 0),
        trigger=TRIGGER_OOB,
    )
    assert row["on_time"] is None


def test_session_writes_record_with_events_and_horizon(runtime):
    with cycle_stats_session(trigger=TRIGGER_QH, version="9.9.9", cold_start=True):
        record_event(EVENT_WEATHER_FETCH)
        record_event(EVENT_WEATHER_FETCH)
        set_horizon_slots(187)
        mark_writes_done()
    rows = load_records()
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == OUTCOME_OK
    assert row["events"] == [EVENT_COLD_START, EVENT_WEATHER_FETCH]
    assert row["horizon_slots"] == 187
    assert row["version"] == "9.9.9"
    assert row["platform"] == stats_mod.platform_info()["id"]
    assert row["writes_done_at"] is not None


def test_session_without_writes_is_no_writes(runtime):
    with cycle_stats_session(trigger=TRIGGER_QH, version="t"):
        pass
    assert load_records()[0]["outcome"] == OUTCOME_NO_WRITES


def test_session_records_error_and_reraises(runtime):
    with pytest.raises(RuntimeError, match="boom"):
        with cycle_stats_session(trigger=TRIGGER_QH, version="t"):
            raise RuntimeError("boom")
    assert load_records()[0]["outcome"] == OUTCOME_ERROR


def test_hooks_are_noop_outside_a_cycle(runtime):
    record_event(EVENT_WEATHER_FETCH)
    mark_writes_done()
    set_horizon_slots(3)
    assert not stats_path().is_file()


def test_punctuality_summary_window_and_quantiles():
    now = datetime(2026, 10, 15, 12, 0)
    rows = []
    for i, late in enumerate([1.0, 0.0, 180.0, 240.0]):
        tick = now - timedelta(minutes=15 * i)
        rows.append({"tick": tick.isoformat(), "late_by_sec": late, "on_time": late <= 2.0})
    rows.append({"tick": (now - timedelta(days=2)).isoformat(), "late_by_sec": 999.0, "on_time": False})
    rows.append({"tick": now.isoformat(), "late_by_sec": None, "on_time": None})
    summary = punctuality_summary(rows, now=now, window=timedelta(hours=24))
    assert summary["cycles"] == 4
    assert summary["on_time"] == 2
    assert summary["p95_late_sec"] == 240.0
    week = punctuality_summary(rows, now=now, window=timedelta(days=7))
    assert week["cycles"] == 5


def test_prune_drops_records_beyond_retention(runtime):
    path = stats_path()
    now = datetime(2026, 10, 15, 9, 0)
    old = {"tick": (now - timedelta(days=9)).isoformat(), "on_time": False}
    keep = {"tick": (now - timedelta(days=1)).isoformat(), "on_time": False}
    path.write_text(json.dumps(old) + "\n" + json.dumps(keep) + "\n", encoding="utf-8")
    stats_mod.append_record({"tick": now.isoformat(), "on_time": True})
    ticks = [row["tick"] for row in load_records()]
    assert ticks == [keep["tick"], now.isoformat()]


def test_regular_cycle_logs_punctuality_line(runtime, caplog):
    tick = datetime.now().replace(microsecond=0)
    with caplog.at_level(logging.INFO, logger="cycle_stats"):
        with cycle_stats_session(trigger=TRIGGER_QH, version="t", tick=tick):
            mark_writes_done()
    lines = [r.getMessage() for r in caplog.records if r.name == "cycle_stats"]
    assert any(line.startswith("Pünktlichkeit: Tick ") and "24 h: " in line for line in lines)


def test_outdoor_forecast_cache_miss_reports_weather_fetch(runtime, monkeypatch):
    from data import outdoor_forecast

    monkeypatch.setattr(outdoor_forecast, "_CACHE", {})
    start = datetime(2026, 10, 15, 9, 0)
    hourly = [(start + timedelta(hours=i), 10.0) for i in range(48)]
    monkeypatch.setattr(outdoor_forecast, "_fetch_open_meteo_hourly", lambda *a, **k: hourly)
    with cycle_stats_session(trigger=TRIGGER_QH, version="t") as stats:
        outdoor_forecast.get_hourly_outdoor_forecast_c(
            horizon=2, latitude=47.4, longitude=9.7, start=start
        )
        outdoor_forecast.get_hourly_outdoor_forecast_c(
            horizon=2, latitude=47.4, longitude=9.7, start=start
        )
        assert stats.events == [EVENT_WEATHER_FETCH]


def test_early_start_record_uses_target_tick_and_planned_start():
    tick = datetime(2026, 10, 15, 13, 0)
    stats = CycleStats(
        trigger=TRIGGER_QH,
        started_at=datetime(2026, 10, 15, 12, 59, 0, 300000),
        woke_at=datetime(2026, 10, 15, 12, 59, 0, 100000),
        tick=tick,
        lead_sec=60.0,
    )
    stats.mark_ready(datetime(2026, 10, 15, 12, 59, 20))
    stats.mark_writes_done(datetime(2026, 10, 15, 13, 0, 0, 500000))
    row = stats.to_record(
        outcome=OUTCOME_OK, finished_at=datetime(2026, 10, 15, 13, 0, 4), version="t"
    )
    assert row["tick"].startswith("2026-10-15T13:00:00")
    assert row["lead_sec"] == 60.0
    assert row["wake_delay_sec"] == pytest.approx(0.1)
    assert row["start_delay_sec"] == pytest.approx(0.3)
    assert row["ready_by_sec"] == pytest.approx(-40.0)
    assert row["late_by_sec"] == pytest.approx(0.5)
    assert row["on_time"] is True


def test_early_start_punctuality_line_shows_lead_and_ready(runtime, caplog):
    tick = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=1)
    with caplog.at_level(logging.INFO, logger="cycle_stats"):
        with cycle_stats_session(
            trigger=TRIGGER_QH, version="t", tick=tick, lead_sec=60.0
        ):
            stats_mod.mark_ready()
            mark_writes_done()
    line = next(r.getMessage() for r in caplog.records if "Pünktlichkeit" in r.getMessage())
    assert "Vorlauf 60 s" in line
    assert "Plan fertig" in line
