"""Tests for main.py daemon lifecycle (probe / start conflict / stop)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runtime_store import main_daemon
from runtime_store.persist_paths import daemon_stdio_log_file, log_file
from runtime_store.single_instance import (
    SingleInstanceLock,
    is_pid_alive,
    probe_instance,
)


def test_probe_free_when_no_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    probe = probe_instance("main")
    assert probe.busy is False
    assert probe.pid is None
    assert probe.lock_path == str(tmp_path / "main.lock")


def test_log_paths_are_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    assert os.path.isabs(log_file())
    assert log_file() == str((tmp_path / "earnie.log").resolve())
    assert os.path.isabs(daemon_stdio_log_file())
    assert daemon_stdio_log_file() == str((tmp_path / "main_stdio.log").resolve())


def test_probe_busy_while_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
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
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
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
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    lock = SingleInstanceLock("main")
    lock.acquire()
    try:
        with pytest.raises(main_daemon.DaemonError, match="bereits"):
            main_daemon.start(wait_sec=1.0)
    finally:
        lock.release()


def test_start_captures_stdio_not_devnull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI/auto-start must not discard child stderr (earnie.log diagnose path)."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    root = Path(__file__).resolve().parents[1]
    stub = tmp_path / "main.py"
    stub.write_text(
        "\n".join(
            [
                "import sys, time",
                "sys.path.insert(0, r'%s')" % str(root).replace("\\", "\\\\"),
                "from runtime_store.single_instance import ensure_single_instance",
                "from runtime_store.daemon_heartbeat import touch_daemon_heartbeat",
                "print('stub-stdio-ok', flush=True)",
                "ensure_single_instance('main')",
                "touch_daemon_heartbeat()",
                "time.sleep(60)",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main_daemon, "project_root", lambda: tmp_path)
    monkeypatch.setattr(main_daemon, "python_executable", lambda: sys.executable)

    try:
        st = main_daemon.start(wait_sec=5.0)
        assert st.state == "running"
        stdio = tmp_path / "main_stdio.log"
        assert stdio.is_file()
        text = stdio.read_text(encoding="utf-8")
        assert "main.py spawn" in text
        assert "stub-stdio-ok" in text
    finally:
        if main_daemon.status().state == "running":
            main_daemon.stop(timeout_sec=5.0)


def _stub_main(tmp_path: Path, body: list[str]) -> Path:
    root = Path(__file__).resolve().parents[1]
    stub = tmp_path / "main.py"
    stub.write_text(
        "\n".join(
            [
                "import sys, time",
                "sys.path.insert(0, r'%s')" % str(root).replace("\\", "\\\\"),
                "from runtime_store.single_instance import ensure_single_instance",
                "from runtime_store.daemon_heartbeat import touch_daemon_heartbeat",
                *body,
            ]
        ),
        encoding="utf-8",
    )
    return stub


def test_start_reports_a_daemon_that_dies_after_taking_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B3: the lock is taken early, a startup crash comes after it (F2) - no OK then."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    _stub_main(
        tmp_path,
        [
            "ensure_single_instance('main')",
            "time.sleep(1.0)",
            "raise SystemExit('startup crash after the lock')",
        ],
    )
    monkeypatch.setattr(main_daemon, "project_root", lambda: tmp_path)
    monkeypatch.setattr(main_daemon, "python_executable", lambda: sys.executable)

    with pytest.raises(main_daemon.DaemonError, match="startup crash after the lock"):
        main_daemon.start(wait_sec=8.0)


def test_start_waits_for_the_main_loop_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The daemon counts as started once it reached the main loop (fresh heartbeat)."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    _stub_main(
        tmp_path,
        [
            "ensure_single_instance('main')",
            "time.sleep(1.0)",
            "touch_daemon_heartbeat()",
            "time.sleep(60)",
        ],
    )
    monkeypatch.setattr(main_daemon, "project_root", lambda: tmp_path)
    monkeypatch.setattr(main_daemon, "python_executable", lambda: sys.executable)

    try:
        started = time.monotonic()
        st = main_daemon.start(wait_sec=8.0)
        assert st.state == "running"
        assert time.monotonic() - started >= 0.9
    finally:
        if main_daemon.status().state == "running":
            main_daemon.stop(timeout_sec=5.0)


def test_start_ignores_a_stale_heartbeat_of_an_earlier_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime_store.daemon_heartbeat import touch_daemon_heartbeat

    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    touch_daemon_heartbeat(now_ts=time.time() - 30)
    _stub_main(
        tmp_path,
        [
            "ensure_single_instance('main')",
            "time.sleep(1.0)",
            "raise SystemExit('crash before the loop')",
        ],
    )
    monkeypatch.setattr(main_daemon, "project_root", lambda: tmp_path)
    monkeypatch.setattr(main_daemon, "python_executable", lambda: sys.executable)

    with pytest.raises(main_daemon.DaemonError, match="crash before the loop"):
        main_daemon.start(wait_sec=8.0)


def test_start_stop_with_stub_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spawn a stub that acquires main.lock like main.py, then stop it."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
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
    env["EARNIE_RUNTIME_PATH"] = str(tmp_path)
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
        # stub is our direct child: reap it so a SIGKILL-but-still-zombie PID
        # (os.kill(pid, 0) succeeds for zombies) doesn't read as "alive".
        proc.wait(timeout=5.0)
        assert not is_pid_alive(st.pid)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


def test_maybe_auto_start_respects_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.delenv("EARNIE_AUTO_START_MAIN", raising=False)
    monkeypatch.delenv("EARNIE_AUTO_START_MAIN", raising=False)
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


def test_subprocess_env_sets_stdio_capture_flag() -> None:
    env = main_daemon._subprocess_env()
    assert env.get("EARNIE_DAEMON_STDIO_CAPTURE") == "1"


def test_stdio_rotate_on_spawn_when_oversized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    path = tmp_path / "main_stdio.log"
    path.write_bytes(b"x" * (main_daemon._STDIO_ROTATE_MAX_BYTES + 1))

    handle = main_daemon._open_daemon_stdio()
    try:
        handle.close()
    except OSError:
        pass

    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "main.py spawn" in text
    assert b"x" * 10 not in path.read_bytes()
    archives = sorted(
        p for p in tmp_path.iterdir() if p.name.startswith("main_stdio.log.") and p.is_file()
    )
    assert len(archives) == 1
    assert archives[0].stat().st_size == main_daemon._STDIO_ROTATE_MAX_BYTES + 1


def test_stdio_append_without_rotate_when_small(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    path = tmp_path / "main_stdio.log"
    path.write_text("keep-me\n", encoding="utf-8")

    handle = main_daemon._open_daemon_stdio()
    try:
        handle.close()
    except OSError:
        pass

    text = path.read_text(encoding="utf-8")
    assert text.startswith("keep-me\n")
    assert "main.py spawn" in text
    archives = [
        p for p in tmp_path.iterdir() if p.name.startswith("main_stdio.log.") and p.is_file()
    ]
    assert archives == []


def test_stdio_rotate_on_spawn_when_prior_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    path = tmp_path / "main_stdio.log"
    path.write_text("old-month\n", encoding="utf-8")
    # Force mtime into previous calendar month.
    now = time.time()
    lt = time.localtime(now)
    year, month = lt.tm_year, lt.tm_mon
    if month == 1:
        year -= 1
        month = 12
    else:
        month -= 1
    prior = time.mktime((year, month, 15, 12, 0, 0, -1, -1, -1))
    os.utime(path, (prior, prior))

    assert main_daemon._maybe_rotate_stdio_on_spawn(path, now=now) is True
    assert not path.exists() or path.stat().st_size == 0
    archives = [
        p for p in tmp_path.iterdir() if p.name.startswith("main_stdio.log.") and p.is_file()
    ]
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8") == "old-month\n"


def test_stdio_prune_keeps_max_12_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    path = tmp_path / "main_stdio.log"
    for i in range(12):
        stamp = f"2025-01-{i + 1:02d}_00-00-00"
        (tmp_path / f"main_stdio.log.{stamp}").write_text(f"old-{i}\n", encoding="utf-8")
    path.write_bytes(b"y" * (main_daemon._STDIO_ROTATE_MAX_BYTES + 1))

    assert main_daemon._maybe_rotate_stdio_on_spawn(path) is True
    archives = sorted(
        p for p in tmp_path.iterdir() if p.name.startswith("main_stdio.log.") and p.is_file()
    )
    assert len(archives) == 12
    assert not any(p.name.endswith("2025-01-01_00-00-00") for p in archives)
