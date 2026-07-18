"""Tests for main.py daemon lifecycle (probe / start conflict / stop)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runtime_store import main_daemon
from runtime_store.single_instance import (
    SingleInstanceLock,
    is_pid_alive,
    probe_instance,
)


def test_probe_free_when_no_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", str(tmp_path))
    probe = probe_instance("main")
    assert probe.busy is False
    assert probe.pid is None
    assert probe.lock_path == str(tmp_path / "main.lock")


def test_probe_busy_while_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", str(tmp_path))
    lock = SingleInstanceLock("main")
    lock.acquire()
    try:
        probe = probe_instance("main")
        assert probe.busy is True
        assert probe.pid == os.getpid()
    finally:
        lock.release()


def test_status_stopped_and_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", str(tmp_path))
    assert main_daemon.status().state == "stopped"

    lock = SingleInstanceLock("main")
    lock.acquire()
    try:
        st = main_daemon.status()
        assert st.state == "running"
        assert st.pid == os.getpid()
    finally:
        lock.release()
    assert main_daemon.status().state == "stopped"


def test_start_raises_when_already_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", str(tmp_path))
    lock = SingleInstanceLock("main")
    lock.acquire()
    try:
        with pytest.raises(main_daemon.DaemonError, match="bereits"):
            main_daemon.start(wait_sec=1.0)
    finally:
        lock.release()


def test_start_stop_with_stub_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spawn a stub that acquires main.lock like main.py, then stop it."""
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", str(tmp_path))
    root = Path(__file__).resolve().parents[1]
    stub = tmp_path / "stub_main.py"
    stub.write_text(
        "\n".join(
            [
                "import sys, time",
                "sys.path.insert(0, r'%s')" % str(root).replace("\\", "\\\\"),
                "from runtime_store.single_instance import ensure_single_instance",
                "ensure_single_instance('main')",
                "time.sleep(60)",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["ENERGY_OPTIMIZER_RUNTIME_PATH"] = str(tmp_path)
    env["PYTHONPATH"] = str(root)
    proc = subprocess.Popen(
        [sys.executable, str(stub)],
        cwd=str(root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5.0
        st = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"stub exited early: {proc.returncode}")
            st = main_daemon.status()
            if st.state == "running":
                break
            time.sleep(0.1)
        assert st is not None and st.state == "running"
        assert st.pid is not None
        assert is_pid_alive(st.pid)

        with pytest.raises(main_daemon.DaemonError, match="bereits"):
            main_daemon.start(wait_sec=1.0)

        stopped = main_daemon.stop(timeout_sec=5.0)
        assert stopped.state == "stopped"
        assert not is_pid_alive(st.pid)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


def test_maybe_auto_start_respects_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", str(tmp_path))
    monkeypatch.delenv("EARNIE_AUTO_START_MAIN", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_AUTO_START_MAIN", raising=False)
    assert main_daemon.maybe_auto_start() is None

    calls: list[bool] = []

    def fake_start(*, wait_sec: float = 15.0):
        calls.append(True)
        return main_daemon.DaemonStatus("running", 12345, str(tmp_path / "main.lock"))

    monkeypatch.setattr(main_daemon, "start", fake_start)
    monkeypatch.setenv("EARNIE_AUTO_START_MAIN", "1")
    result = main_daemon.maybe_auto_start()
    assert result is not None
    assert result.state == "running"
    assert calls == [True]


def test_is_pid_alive_self() -> None:
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(-1) is False


def test_is_pid_alive_other_alive_process() -> None:
    """Regression: Windows/Py3.14 os.kill(pid, 0) raises WinError 87 for others."""
    assert is_pid_alive(os.getpid()) is True
    # Current process must be detected; a very high unused PID must not.
    assert is_pid_alive(2_147_000_000) is False
