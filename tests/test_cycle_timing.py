"""Env-gated cycle timing helper (EARNIE_CYCLE_TIMING / EARNIE_CYCLE_PROFILE)."""
from __future__ import annotations

import json
import time

from runtime_store.cycle_timing import (
    CycleTimer,
    cycle_session,
    jsonl_path,
    profile_dir,
    record_phase,
    timing_enabled,
)


def test_timing_disabled_is_noop(monkeypatch, tmp_path):
    monkeypatch.delenv("EARNIE_CYCLE_TIMING", raising=False)
    monkeypatch.delenv("EARNIE_CYCLE_PROFILE", raising=False)
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    assert timing_enabled() is False
    with cycle_session(slot_key="2026-10-15T10:00") as timing:
        with timing.phase("milp_live"):
            time.sleep(0.01)
        with record_phase("savings_optimized"):
            time.sleep(0.01)
    assert not jsonl_path().is_file()
    assert timing.phases == {}


def test_timing_writes_jsonl_and_accumulates_phases(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_CYCLE_TIMING", "1")
    monkeypatch.delenv("EARNIE_CYCLE_PROFILE", raising=False)
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    with cycle_session(slot_key="2026-10-15T10:15") as timing:
        with timing.phase("ehal_read"):
            time.sleep(0.01)
        with timing.phase("ehal_read"):
            time.sleep(0.01)
        with record_phase("savings_optimized"):
            time.sleep(0.01)
    path = jsonl_path()
    assert path.is_file()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    phases = rows[0]["phases_sec"]
    assert rows[0]["slot"] == "2026-10-15T10:15"
    assert phases["ehal_read"] >= 0.015
    assert phases["savings_optimized"] >= 0.005
    assert phases["total"] >= phases["ehal_read"]
    assert rows[0]["profile"] is False


def test_profile_dumps_prof_and_pstats(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_CYCLE_TIMING", "1")
    monkeypatch.setenv("EARNIE_CYCLE_PROFILE", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    with cycle_session(slot_key="2026-10-15T10:30") as timing:
        with timing.phase("milp_live"):
            sum(range(2000))
    profs = list(profile_dir().glob("cycle_*.prof"))
    texts = list(profile_dir().glob("cycle_*_top30.txt"))
    assert len(profs) == 1
    assert len(texts) == 1
    assert "cumulative" in texts[0].read_text(encoding="utf-8").lower() or texts[
        0
    ].stat().st_size > 0


def test_finish_without_activate_when_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("EARNIE_CYCLE_TIMING", raising=False)
    monkeypatch.delenv("EARNIE_CYCLE_PROFILE", raising=False)
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    timer = CycleTimer(slot_key="x")
    assert timer.finish() is None
    assert not jsonl_path().is_file()
