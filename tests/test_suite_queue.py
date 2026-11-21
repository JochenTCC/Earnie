"""Tests for scripts.suite_queue (machine-wide FIFO queue for test runs)."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from scripts import suite_queue as tq

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def qdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "queue"
    monkeypatch.setenv(tq.QUEUE_DIR_ENV, str(directory))
    monkeypatch.delenv(tq.HELD_ENV, raising=False)
    monkeypatch.delenv(tq.DISABLE_ENV, raising=False)
    return directory


def _ticket(directory: Path, name: str, pid: int, **extra: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}{tq.TICKET_SUFFIX}"
    data = {"pid": pid, "label": name, "cwd": "/x", "created": time.time(), **extra}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_queue_dir_override(qdir: Path) -> None:
    assert tq.queue_dir() == qdir


def test_pid_alive_self_and_dead() -> None:
    assert tq.pid_alive(os.getpid())
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert not tq.pid_alive(proc.pid)
    assert not tq.pid_alive(0)


def test_live_tickets_prunes_dead_and_stale(qdir: Path) -> None:
    alive = _ticket(qdir, "00000000000000000001-a", os.getpid())
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead = _ticket(qdir, "00000000000000000002-b", proc.pid)
    stale = _ticket(qdir, "00000000000000000003-c", os.getpid())
    old = time.time() - tq.STALE_SECONDS - 10
    os.utime(stale, (old, old))

    tickets = tq.live_tickets(qdir)

    assert [t.path for t in tickets] == [alive]
    assert not dead.exists()
    assert not stale.exists()


def test_slot_noop_when_disabled_or_held(qdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(tq.DISABLE_ENV, "off")
    with tq.queued_slot("x"):
        assert not qdir.exists()
    monkeypatch.delenv(tq.DISABLE_ENV)
    monkeypatch.setenv(tq.HELD_ENV, "1")
    with tq.queued_slot("x"):
        assert not qdir.exists()


def test_slot_registers_marks_running_and_cleans_up(qdir: Path) -> None:
    with tq.queued_slot("unit run", out=io.StringIO()):
        tickets = tq.live_tickets(qdir)
        assert len(tickets) == 1
        assert tickets[0].label == "unit run"
        assert tickets[0].running_since is not None
        assert os.environ[tq.HELD_ENV] == "1"
    assert tq.live_tickets(qdir) == []
    assert tq.HELD_ENV not in os.environ


def test_slot_waits_behind_older_live_ticket(
    qdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older = _ticket(qdir, "00000000000000000001-older", os.getpid(), running_since=time.time())
    out = io.StringIO()
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        older.unlink()  # the run ahead finishes

    monkeypatch.setattr(tq.time, "sleep", fake_sleep)
    with tq.queued_slot("mine", out=out, poll_seconds=0.01):
        pass

    assert sleeps, "must have waited for the older ticket"
    text = out.getvalue()
    assert "position 2/2" in text
    assert "ahead: 00000000000000000001-older" in text


_HOLDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from scripts.suite_queue import queued_slot
    marker = Path(sys.argv[1])
    with queued_slot("holder"):
        marker.write_text("in", encoding="utf-8")
        time.sleep(float(sys.argv[2]))
        # Still inside the slot: written before the release in queued_slot's finally.
        Path(str(marker) + ".leaving").write_text("leaving", encoding="utf-8")
    """
)


def test_lock_excludes_second_process(qdir: Path, tmp_path: Path) -> None:
    """A second run must not start while another process holds the slot.

    The check is the holder's "leaving" marker, written inside the slot right before
    the release. Whether the holder process has already exited is no criterion: the
    slot is released before interpreter shutdown, which takes longer under load.
    """
    marker = tmp_path / "holder.marker"
    leaving = Path(str(marker) + ".leaving")
    env = {**os.environ, tq.QUEUE_DIR_ENV: str(qdir)}
    env.pop(tq.HELD_ENV, None)
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(marker), "3"], cwd=ROOT, env=env
    )
    try:
        deadline = time.time() + 30
        while not marker.exists():
            assert time.time() < deadline, "holder never got the slot"
            assert holder.poll() is None, "holder exited early"
            time.sleep(0.05)
        started = time.time()
        with tq.queued_slot("second", out=io.StringIO(), poll_seconds=0.05):
            entered = time.time()
            assert leaving.exists(), "slot granted while holder still held it"
        assert entered - started > 0.5
    finally:
        holder.kill()
        holder.wait()


def test_killed_holder_does_not_block(qdir: Path, tmp_path: Path) -> None:
    marker = tmp_path / "holder.marker"
    env = {**os.environ, tq.QUEUE_DIR_ENV: str(qdir)}
    env.pop(tq.HELD_ENV, None)
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(marker), "600"], cwd=ROOT, env=env
    )
    deadline = time.time() + 30
    while not marker.exists():
        assert time.time() < deadline, "holder never got the slot"
        time.sleep(0.05)
    holder.kill()
    holder.wait()
    with tq.queued_slot("after kill", out=io.StringIO(), poll_seconds=0.05):
        assert len(tq.live_tickets(qdir)) == 1


def test_status_lines(qdir: Path) -> None:
    assert "idle" in tq.status_lines()[0]
    _ticket(qdir, "00000000000000000001-a", os.getpid(), running_since=time.time())
    lines = tq.status_lines()
    assert "1 run(s)" in lines[0]
    assert "running" in lines[1]
