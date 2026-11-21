"""Machine-wide FIFO queue for heavy test runs (pytest suite, regression suite).

Several agent sessions (and the git hooks) on one PC used to start the test
suite in parallel. Each run spawns ``-n auto`` xdist workers, so concurrent
runs overload the CPU: slow runs and timing-related false failures. This
module serialises them across all checkouts and worktrees of the machine:

* Every run drops a **ticket** into the queue directory; tickets are ordered by
  creation time (FIFO). Only the oldest live ticket may start.
* The run additionally holds an OS file lock (``run.lock``) while it executes.
  The lock is the hard mutual-exclusion guarantee (the OS frees it when the
  process dies); the ticket order only provides fairness and status output.
* A heartbeat thread touches the ticket every few seconds. A ticket whose
  process is gone or whose heartbeat is older than ``STALE_SECONDS`` is
  removed by the next waiter, so crashed or killed runs never block the queue.
* Child processes inherit ``EARNIE_TEST_QUEUE_HELD=1``; nested runs (a test or
  hook that starts the wrapper again) do not queue a second time.

Queue directory: ``$EARNIE_TEST_QUEUE_DIR``, default
``%LOCALAPPDATA%\\earnie\\test-queue`` (Windows) or
``$XDG_CACHE_HOME/earnie/test-queue`` (``~/.cache`` fallback). It lives outside
any repository on purpose, so every worktree shares the same queue.

``EARNIE_TEST_QUEUE=off`` disables queueing (one-off escape hatch, e.g. CI
containers that run only one suite anyway).

CLI::

    python -m scripts.suite_queue status   # show running / waiting runs
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

QUEUE_DIR_ENV = "EARNIE_TEST_QUEUE_DIR"
DISABLE_ENV = "EARNIE_TEST_QUEUE"
HELD_ENV = "EARNIE_TEST_QUEUE_HELD"

HEARTBEAT_SECONDS = 5.0
STALE_SECONDS = 60.0
POLL_SECONDS = 2.0
STATUS_EVERY_SECONDS = 30.0
LOCK_NAME = "run.lock"
TICKET_SUFFIX = ".ticket.json"


def queue_disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() in {"off", "0", "false", "no"}


def queue_held() -> bool:
    return os.environ.get(HELD_ENV) == "1"


def queue_dir() -> Path:
    override = os.environ.get(QUEUE_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "earnie" / "test-queue"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "earnie" / "test-queue"


# --------------------------------------------------------------------------- #
# Process liveness
# --------------------------------------------------------------------------- #


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:  # pragma: no cover - Windows only
    # os.kill(pid, 0) is NOT a probe on Windows (signal 0 == CTRL_C_EVENT).
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


# --------------------------------------------------------------------------- #
# File lock
# --------------------------------------------------------------------------- #


class _RunLock:
    """Non-blocking exclusive lock on ``run.lock``; released by the OS on exit."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh: IO[bytes] | None = None

    def try_acquire(self) -> bool:
        fh = open(self._path, "a+b")  # noqa: SIM115 - held until release()
        try:
            if sys.platform == "win32":  # pragma: no cover - Windows only
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if sys.platform == "win32":  # pragma: no cover - Windows only
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


# --------------------------------------------------------------------------- #
# Tickets
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Ticket:
    path: Path
    pid: int
    label: str
    cwd: str
    created: float
    running_since: float | None

    @property
    def sort_key(self) -> str:
        return self.path.name


def _read_ticket(path: Path) -> Ticket | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return Ticket(
            path=path,
            pid=int(data["pid"]),
            label=str(data.get("label", "")),
            cwd=str(data.get("cwd", "")),
            created=float(data.get("created", 0.0)),
            running_since=(
                float(data["running_since"]) if data.get("running_since") is not None else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _is_stale(ticket: Ticket, now: float) -> bool:
    if not pid_alive(ticket.pid):
        return True
    try:
        age = now - ticket.path.stat().st_mtime
    except OSError:
        return True
    return age > STALE_SECONDS


def live_tickets(directory: Path, *, prune: bool = True) -> list[Ticket]:
    """Return live tickets in FIFO order; stale/unreadable ones are removed."""
    if not directory.is_dir():
        return []
    now = time.time()
    tickets: list[Ticket] = []
    for path in sorted(directory.glob(f"*{TICKET_SUFFIX}")):
        ticket = _read_ticket(path)
        if ticket is None:
            # Unreadable: half-written by a dying process, or not ours. Remove
            # only once it is old, a fresh one may still be in os.replace().
            try:
                if prune and now - path.stat().st_mtime > STALE_SECONDS:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        if _is_stale(ticket, now):
            if prune:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            continue
        tickets.append(ticket)
    return tickets


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def _describe(ticket: Ticket, now: float) -> str:
    if ticket.running_since is not None:
        state = f"running {_fmt_duration(now - ticket.running_since)}"
    else:
        state = f"waiting {_fmt_duration(now - ticket.created)}"
    return f"{ticket.label} (pid {ticket.pid}, {state}, cwd {ticket.cwd})"


class _Heartbeat(threading.Thread):
    def __init__(self, path: Path) -> None:
        super().__init__(name="test-queue-heartbeat", daemon=True)
        self._path = path
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(HEARTBEAT_SECONDS):
            try:
                os.utime(self._path)
            except OSError:
                pass

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=HEARTBEAT_SECONDS * 2)


@contextmanager
def queued_slot(
    label: str,
    *,
    out: IO[str] | None = None,
    poll_seconds: float = POLL_SECONDS,
) -> Iterator[None]:
    """Block until this process may run a heavy test job; hold the slot inside.

    No-op when queueing is disabled or an outer process already holds the slot.
    """
    if queue_disabled() or queue_held():
        yield
        return

    stream = out if out is not None else sys.stderr
    directory = queue_dir()
    directory.mkdir(parents=True, exist_ok=True)
    created = time.time()
    ticket_path = directory / f"{time.time_ns():020d}-{os.getpid():08d}{TICKET_SUFFIX}"
    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "label": label,
        "cwd": os.getcwd(),
        "created": created,
        "running_since": None,
    }
    _write_json_atomic(ticket_path, payload)
    heartbeat = _Heartbeat(ticket_path)
    heartbeat.start()
    lock = _RunLock(directory / LOCK_NAME)
    previous_held = os.environ.get(HELD_ENV)
    acquired = False
    try:
        last_status = ""
        last_status_at = 0.0
        while True:
            tickets = live_tickets(directory)
            names = [t.path.name for t in tickets]
            if ticket_path.name not in names:
                # Pruned by someone (e.g. heartbeat hiccup): re-register in place.
                _write_json_atomic(ticket_path, payload)
                continue
            position = names.index(ticket_path.name)
            if position == 0 and lock.try_acquire():
                acquired = True
                break
            now = time.time()
            running = [t for t in tickets if t.running_since is not None]
            ahead = tickets[:position] if position else running
            status = f"position {position + 1}/{len(tickets)}"
            if status != last_status or now - last_status_at >= STATUS_EVERY_SECONDS:
                lines = [f"[test-queue] waiting ({status}) - {label}"]
                for other in ahead:
                    lines.append(f"[test-queue]   ahead: {_describe(other, now)}")
                print("\n".join(lines), file=stream, flush=True)
                last_status, last_status_at = status, now
            time.sleep(poll_seconds)

        waited = time.time() - created
        if waited >= 1.0:
            print(
                f"[test-queue] starting after {_fmt_duration(waited)} wait - {label}",
                file=stream,
                flush=True,
            )
        payload["running_since"] = time.time()
        _write_json_atomic(ticket_path, payload)
        os.environ[HELD_ENV] = "1"
        yield
    finally:
        if previous_held is None:
            os.environ.pop(HELD_ENV, None)
        else:
            os.environ[HELD_ENV] = previous_held
        heartbeat.stop()
        try:
            ticket_path.unlink(missing_ok=True)
        except OSError:
            pass
        if acquired:
            lock.release()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def status_lines(directory: Path | None = None) -> list[str]:
    directory = directory or queue_dir()
    tickets = live_tickets(directory)
    if not tickets:
        return [f"[test-queue] idle ({directory})"]
    now = time.time()
    lines = [f"[test-queue] {len(tickets)} run(s) in {directory}"]
    for index, ticket in enumerate(tickets, start=1):
        lines.append(f"  {index}. {_describe(ticket, now)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    if command == "status":
        print("\n".join(status_lines()))
        return 0
    print("usage: python -m scripts.suite_queue [status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
