"""Live month peak of grid import (max-power tariff P5a)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import main as main_module
from runtime_store import capacity_peak_store as store
from runtime_store.power_interval_sampler import (
    GRID_IMPORT_SOURCE_COUNTER,
    GRID_IMPORT_SOURCE_MEAN,
)

START = datetime(2026, 11, 30, 23, 0)


def _closed(
    slot: datetime, kw: float, *, source=GRID_IMPORT_SOURCE_COUNTER, samples=30, window_s=870
) -> dict:
    opened = slot + timedelta(seconds=30)
    return {
        "interval_start": slot.isoformat(),
        "sample_count": samples,
        "grid_import_kw": kw,
        "grid_import_source": source,
        "grid_import_start": opened.isoformat(),
        "grid_import_end": (opened + timedelta(seconds=window_s)).isoformat(),
    }


def _record(path: Path, offset_min: int, kw: float, **kwargs):
    slot = START + timedelta(minutes=offset_min)
    return store.record_closed_interval(_closed(slot, kw, **kwargs), path=str(path))


def test_the_month_keeps_its_peak_and_counts_missed_quarter_hours_across_a_restart(tmp_path: Path):
    path = tmp_path / "peaks.json"
    _record(path, 0, 2.0)
    _record(path, 15, 4.5, source=GRID_IMPORT_SOURCE_MEAN)
    _record(path, 45, 3.0)  # 23:30 was not logged
    peak = store.month_peak("2026-11", path=str(path))  # read back from disk, as after a restart
    assert peak == store.MonthPeak(
        month="2026-11",
        peak_kw=4.5,
        peak_slot="2026-11-30T23:15:00",
        peak_source=GRID_IMPORT_SOURCE_MEAN,
        first_slot="2026-11-30T23:00:00",
        last_slot="2026-11-30T23:45:00",
        slots_logged=3,
        slots_missing=1,
    )


def test_a_new_month_starts_its_own_entry_and_keeps_the_old_one(tmp_path: Path):
    path = tmp_path / "peaks.json"
    _record(path, 45, 6.0)
    december = _record(path, 60, 1.0)
    assert (december.month, december.peak_kw, december.first_slot, december.slots_missing) == (
        "2026-12",
        1.0,
        "2026-12-01T00:00:00",
        0,
    )
    assert store.month_peak("2026-11", path=str(path)).peak_kw == 6.0


def test_an_unmeasured_month_is_unknown_not_zero(tmp_path: Path):
    assert store.month_peak("2026-11", path=str(tmp_path / "peaks.json")) is None


def test_a_mean_of_too_few_samples_counts_as_missing(tmp_path: Path):
    path = tmp_path / "peaks.json"
    assert _record(path, 0, 9.0, source=GRID_IMPORT_SOURCE_MEAN, samples=2) is None
    _record(path, 15, 2.0)
    peak = _record(path, 30, 9.0, source=GRID_IMPORT_SOURCE_MEAN, samples=1)
    assert (peak.peak_kw, peak.first_slot, peak.slots_logged, peak.slots_missing) == (
        2.0,
        "2026-11-30T23:15:00",
        1,
        1,
    )


def test_a_mean_over_the_last_minute_after_a_restart_counts_as_missing(tmp_path: Path):
    """Seen on the HA testbed: three samples in the last 35 s of the slot marked it as measured."""
    path = tmp_path / "peaks.json"
    assert _record(path, 0, 0.0, source=GRID_IMPORT_SOURCE_MEAN, samples=3, window_s=35) is None
    peak = _record(path, 15, 0.3)
    assert (peak.first_slot, peak.slots_logged, peak.slots_missing) == ("2026-11-30T23:15:00", 1, 0)


def test_a_slot_not_after_the_last_one_changes_nothing(tmp_path: Path, caplog):
    path = tmp_path / "peaks.json"
    _record(path, 30, 2.0)
    with caplog.at_level(logging.WARNING):
        peak = _record(path, 15, 8.0)
    assert (peak.peak_kw, peak.last_slot, peak.slots_logged) == (2.0, "2026-11-30T23:30:00", 1)
    assert "not after the last stored" in caplog.text


def test_a_closed_interval_without_import_fails_loud(tmp_path: Path):
    with pytest.raises(ValueError, match="no grid import"):
        store.record_closed_interval(
            {"interval_start": START.isoformat(), "sample_count": 30}, path=str(tmp_path / "p.json")
        )


def test_the_live_cycle_records_each_closed_quarter_hour(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    closed = _closed(START, 3.3)
    monkeypatch.setattr(
        main_module.power_interval_sampler, "finalize_closed_interval", lambda _slot: closed
    )
    assert main_module._finalize_previous_interval() is closed
    assert store.month_peak("2026-11").peak_kw == 3.3


def test_a_store_failure_does_not_stop_the_cycle(monkeypatch, caplog, tmp_path: Path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    broken = {"interval_start": START.isoformat(), "sample_count": 30}
    monkeypatch.setattr(
        main_module.power_interval_sampler, "finalize_closed_interval", lambda _slot: broken
    )
    with caplog.at_level(logging.WARNING, logger="main"):
        assert main_module._finalize_previous_interval() is broken
    assert "not recorded" in caplog.text


def _utc_host(monkeypatch):
    """A container with TZ=UTC for a plant in Europe/Vienna: naive host times are UTC."""
    from datetime import timezone

    import config

    monkeypatch.setattr(
        store, "_host_aware", lambda moment: moment.replace(tzinfo=timezone.utc)
    )
    monkeypatch.setattr(config, "get_planning_timezone", lambda: "Europe/Vienna")


def test_the_month_follows_the_planning_timezone_not_the_host_clock(tmp_path: Path, monkeypatch):
    """Host 2026-11-30 23:15 UTC is 2026-12-01 00:15 in Vienna: the operator bills it to December."""
    _utc_host(monkeypatch)
    path = tmp_path / "peaks.json"
    peak = store.record_closed_interval(_closed(START + timedelta(minutes=15), 7.0), path=str(path))
    assert (peak.month, peak.peak_slot) == ("2026-12", "2026-12-01T00:15:00")
    assert store.month_peak("2026-11", path=str(path)) is None
    assert store.planning_month("2026-11-30T23:15:00") == "2026-12"


def test_main_reads_the_month_before_in_the_planning_timezone(tmp_path: Path, monkeypatch):
    """The cap check compares with the peak of the slot's billing month (planning timezone)."""
    _utc_host(monkeypatch)
    seen = []
    monkeypatch.setattr(store, "month_peak", lambda month, **_: seen.append(month))
    monkeypatch.setattr(store, "record_closed_interval", lambda closed, **_: None)
    monkeypatch.setattr(main_module.config, "get_resolved_runtime_settings", lambda: {})
    main_module._record_month_peak(_closed(START + timedelta(minutes=15), 7.0))
    assert seen == ["2026-12"]


def test_monitor_and_scenario_check_take_today_from_the_planning_timezone(monkeypatch):
    """At 23:30 UTC on 30 November it is already 1 December in Vienna (Monitor month, cap check)."""
    from datetime import timezone

    _utc_host(monkeypatch)
    now = store.planning_now(datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc))
    assert now == datetime(2026, 12, 1, 0, 30)
    assert store.planning_now(datetime(2026, 11, 30, 23, 30)).date().isoformat() == "2026-12-01"
