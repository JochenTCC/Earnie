"""Regression tests for the runtime_store review of 2026-11-21 (persistence fixes)."""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta

import pytest

from runtime_store import cycle_recorder, ev_assignments, power_interval_sampler
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from runtime_store.migration import io_util
from runtime_store.version_track import is_downgrade


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        ("2.8.0-dev.30", "2.8.0-dev.9", False),
        ("2.8.0-dev.9", "2.8.0-dev.30", True),
        ("2.8.0-dev.10", "2.8.0-dev.10", False),
        ("2.8.0-beta.1", "2.8.0-alpha.9", False),
        ("2.8.0-alpha.9", "2.8.0-beta.1", True),
        ("2.8.0-dev.30", "2.8.0", True),
    ],
)
def test_downgrade_compares_pre_release_numbers_as_numbers(current, previous, expected):
    assert is_downgrade(current, previous) is expected


def test_load_state_raises_on_read_error_and_keeps_the_file(tmp_path, monkeypatch):
    """A read error says nothing about the content: the chain must not restart."""
    path = tmp_path / "savings_ledger_state.json"
    path.write_text("{}", encoding="utf-8")
    real_open = open

    def failing_open(file, *args, **kwargs):
        if str(file) == str(path):
            raise OSError("mount is away")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", failing_open)

    with pytest.raises(OSError, match="mount is away"):
        store.load_state(str(path))

    assert path.is_file()
    assert not list(tmp_path.glob("*.broken-*"))


def test_last_line_has_day_finds_the_day_a_restart_would_append_again(tmp_path):
    path = tmp_path / "savings_ledger.jsonl"
    assert store.last_line_has_day(str(path), "d2", "c1") is False
    store.append_row({"day_start": "d1", "chain_start": "c1"}, str(path))
    store.append_row({"day_start": "d2", "chain_start": "c1"}, str(path))

    assert store.last_line_has_day(str(path), "d2", "c1") is True
    assert store.last_line_has_day(str(path), "d1", "c1") is False
    assert store.last_line_has_day(str(path), "d2", "c2") is False


def test_replace_pack_docs_restores_written_files_when_a_later_write_fails(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"old": 1}\n', encoding="utf-8")
    (tmp_path / "house_profiles.json").write_text('{"old": 2}\n', encoding="utf-8")
    real_write = io_util.write_json_atomic

    def failing_write(path, doc):
        if path.name == "house_profiles.json":
            raise OSError("disk full")
        real_write(path, doc)

    monkeypatch.setattr(io_util, "write_json_atomic", failing_write)

    with pytest.raises(OSError, match="disk full"):
        io_util.replace_pack_docs(
            tmp_path,
            {"config.json": {"new": 1}, "components.json": {"new": 3}, "house_profiles.json": {"new": 2}},
        )

    assert (tmp_path / "config.json").read_text(encoding="utf-8") == '{"old": 1}\n'
    assert (tmp_path / "house_profiles.json").read_text(encoding="utf-8") == '{"old": 2}\n'
    assert not (tmp_path / "components.json").exists()


def _sample(ts: str) -> dict:
    return {"ts": ts, "pv_kw": 1.0, "grid_kw": 0.5, "battery_kw": 0.0, "house_kw": 1.5, "flex_kw": {}}


def test_finalize_drops_samples_and_anchors_of_older_slots_and_writes_atomically(tmp_path):
    path = tmp_path / "sampler.json"
    power_interval_sampler._save_state(
        str(path),
        {
            "samples": [
                _sample("2026-11-02T09:31:00"),  # slot no cycle closed
                _sample("2026-11-02T10:00:10"),
                _sample("2026-11-02T10:05:10"),
                _sample("2026-11-02T10:10:10"),
                _sample("2026-11-02T10:15:05"),  # open slot
            ],
            "energy_anchors": {
                "2026-11-02T09:30:00": {"open": {}, "open_ts": "2026-11-02T09:30:05"},
                "2026-11-02T10:15:00": {"open": {}, "open_ts": "2026-11-02T10:15:05"},
            },
        },
    )
    assert not (tmp_path / "sampler.json.tmp").exists()

    closed = power_interval_sampler.finalize_closed_interval(
        datetime(2026, 11, 2, 10, 0), state_path=str(path), read_energy=lambda: None
    )

    assert closed["sample_count"] == 3
    state = json.loads(path.read_text(encoding="utf-8"))
    assert [s["ts"] for s in state["samples"]] == ["2026-11-02T10:15:05"]
    assert list(state["energy_anchors"]) == ["2026-11-02T10:15:00"]


def test_consume_picks_takes_the_file_and_keeps_a_later_pick(tmp_path, monkeypatch):
    monkeypatch.setattr(ev_assignments, "_path", lambda name: str(tmp_path / name))
    assert ev_assignments.consume_picks() == []

    ev_assignments.request_pick("wb1", "ev1", "s1")
    assert [p["ev_id"] for p in ev_assignments.consume_picks()] == ["ev1"]
    assert ev_assignments.consume_picks() == []
    assert not list(tmp_path.iterdir())

    ev_assignments.request_pick("wb1", "ev2", "s2")
    assert [p["ev_id"] for p in ev_assignments.consume_picks()] == ["ev2"]


def test_prune_removes_snapshots_not_used_since_the_oldest_kept_segment(tmp_path, monkeypatch):
    monkeypatch.setattr(cycle_recorder, "recorder_dir", lambda: tmp_path)
    configs = tmp_path / "configs"
    configs.mkdir()
    old, used = configs / "old.json", configs / "used.json"
    for path in (old, used):
        path.write_text("{}", encoding="utf-8")
    long_ago = time.time() - 30 * 86400
    os.utime(old, (long_ago, long_ago))
    stale_day = date.today() - timedelta(days=30)
    (tmp_path / f"cycles_{stale_day.isoformat()}.jsonl.gz").write_bytes(b"")
    (tmp_path / f"cycles_{date.today().isoformat()}.jsonl.gz").write_bytes(b"")

    removed = cycle_recorder.prune_old_segments(keep_days=7)

    assert {p.name for p in removed} == {f"cycles_{stale_day.isoformat()}.jsonl.gz", "old.json"}
    assert used.is_file() and not old.exists()


def test_existing_snapshot_is_touched_so_it_counts_as_used(tmp_path, monkeypatch):
    monkeypatch.setattr(cycle_recorder, "recorder_dir", lambda: tmp_path)
    configs = tmp_path / "configs"
    configs.mkdir()
    snapshot = configs / "abc.json"
    snapshot.write_text("{}", encoding="utf-8")
    long_ago = time.time() - 30 * 86400
    os.utime(snapshot, (long_ago, long_ago))

    cycle_recorder._ensure_config_snapshot("abc")

    assert date.fromtimestamp(snapshot.stat().st_mtime) == date.today()


def test_chain_reason_constant_is_stable():
    assert sl.CHAIN_BATTERY_CHANGED == "battery_changed"
