"""EarlyStart P1: adaptive lead (60–90 s), env switch, next start."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer import start_scheduler as ss


def _record(
    plan_sec: float,
    *,
    trigger: str = "quarter_hour",
    outcome: str = "ok",
    platform: str = "p1",
    ready: bool = True,
) -> dict:
    started = datetime(2026, 10, 15, 12, 29, 0)
    done = started + timedelta(seconds=plan_sec)
    return {
        "trigger": trigger,
        "outcome": outcome,
        "platform": platform,
        "started_at": started.isoformat(),
        "ready_at": done.isoformat() if ready else None,
        "writes_done_at": (done + timedelta(seconds=1)).isoformat(),
    }


def test_early_start_env_default_on_and_off(monkeypatch):
    monkeypatch.delenv(ss.EARLY_START_ENV, raising=False)
    assert ss.early_start_enabled()
    monkeypatch.setenv(ss.EARLY_START_ENV, "off")
    assert not ss.early_start_enabled()
    monkeypatch.setenv(ss.EARLY_START_ENV, " ON ")
    assert ss.early_start_enabled()


def test_early_start_env_rejects_other_values(monkeypatch):
    monkeypatch.setenv(ss.EARLY_START_ENV, "60")
    with pytest.raises(ValueError, match="EARNIE_EARLY_START"):
        ss.early_start_enabled()


def test_off_gives_zero_lead():
    decision = ss.decide_lead([_record(10.0)] * 20, enabled=False)
    assert decision.lead_sec == 0.0
    assert decision.reason == ss.REASON_OFF


def test_bootstrap_with_few_samples_uses_60_s():
    decision = ss.decide_lead([_record(10.0)] * (ss.MIN_SAMPLES - 1))
    assert decision.lead_sec == ss.BOOTSTRAP_LEAD_SEC == 60.0
    assert decision.reason == ss.REASON_BOOTSTRAP


def test_fast_cycles_keep_the_15_s_floor():
    decision = ss.decide_lead([_record(12.0)] * 20)
    assert ss.LEAD_MIN_SEC == 15.0
    assert decision.lead_sec == ss.LEAD_MIN_SEC
    assert decision.reason == ss.REASON_MIN
    assert decision.estimate_sec == pytest.approx(12.0)


def test_measured_nas_cycles_hit_the_15_s_floor():
    # dev.57 NAS, time to plan 8–16 s → median 12.5 s → floor 15 s (start T−15 s).
    records = [_record(v) for v in (14.0, 11.0, 8.0, 16.0, 13.0, 12.0, 15.0, 9.0)]
    assert ss.decide_lead(records).lead_sec == 15.0


def test_median_above_floor_is_used():
    decision = ss.decide_lead([_record(20.0)] * 20)
    assert decision.lead_sec == 20
    assert decision.reason == ss.REASON_ESTIMATE


def test_lead_tracks_the_median_between_bounds():
    records = [_record(40.0)] * 6 + [_record(50.0)] * 5 + [_record(200.0)] * 4
    decision = ss.decide_lead(records)
    assert decision.reason == ss.REASON_ESTIMATE
    assert decision.lead_sec == 50  # median of 15 values


def test_median_minimises_absolute_gap_to_tick():
    durations = [12.0, 14.0, 35.0, 40.0, 45.0, 48.0, 75.0, 80.0, 85.0]
    lead = ss.decide_lead([_record(v) for v in durations]).lead_sec

    def mean_abs_gap(candidate: float) -> float:
        return sum(abs(d - candidate) for d in durations) / len(durations)

    assert lead == 45
    assert all(mean_abs_gap(lead) <= mean_abs_gap(c) for c in range(15, 91))


def test_estimate_above_90_s_is_capped():
    decision = ss.decide_lead([_record(120.0)] * 20)
    assert decision.lead_sec == ss.LEAD_MAX_SEC
    assert decision.capped
    assert decision.estimate_sec > ss.LEAD_MAX_SEC


def test_rare_outliers_do_not_move_the_lead():
    records = [_record(15.0)] * 90 + [_record(300.0)] * 6
    assert ss.decide_lead(records).lead_sec == ss.LEAD_MIN_SEC


def test_cold_start_records_are_ignored_by_decide_lead():
    """A restart's time to plan (imports, archive) must not pull the median up."""
    normal = [_record(12.0) for _ in range(ss.MIN_SAMPLES)]
    cold = []
    for _ in range(ss.MIN_SAMPLES):
        row = _record(40.0)
        row["events"] = ["cold_start"]
        cold.append(row)
    decision = ss.decide_lead(normal + cold, platform="p1")
    assert ss.plan_durations(normal + cold, platform="p1") == [12.0] * ss.MIN_SAMPLES
    assert decision.samples == ss.MIN_SAMPLES
    assert decision.lead_sec == ss.LEAD_MIN_SEC
    assert decision.estimate_sec == pytest.approx(12.0)


def test_only_regular_ok_cycles_on_this_platform_count():
    records = [_record(15.0)] * 10 + [
        _record(200.0, trigger="request_optimize"),
        _record(200.0, outcome="no_writes"),
        _record(200.0, platform="other"),
    ] * 10
    assert ss.decide_lead(records, platform="p1").lead_sec == 15


def test_old_records_without_ready_use_writes_done():
    assert ss.time_to_plan_sec(_record(20.0, ready=False)) == pytest.approx(21.0)


def test_next_regular_start_regular_and_hour_rollover():
    tick, start = ss.next_regular_start(datetime(2026, 10, 15, 12, 45, 10), 60)
    assert tick == datetime(2026, 10, 15, 13, 0)
    assert start == datetime(2026, 10, 15, 12, 59)


def test_next_regular_start_midnight():
    tick, start = ss.next_regular_start(datetime(2026, 10, 15, 23, 50), 90)
    assert tick == datetime(2026, 10, 16, 0, 0)
    assert start == datetime(2026, 10, 15, 23, 58, 30)


def test_next_regular_start_inside_lead_window_starts_now():
    now = datetime(2026, 10, 15, 12, 59, 30)
    tick, start = ss.next_regular_start(now, 60)
    assert tick == datetime(2026, 10, 15, 13, 0)
    assert start == now
