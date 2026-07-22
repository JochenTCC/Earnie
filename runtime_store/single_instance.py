"""Verhindert parallele Instanzen desselben Hintergrunddienstes."""
from __future__ import annotations

import atexit
import logging
import os
import sys
from dataclasses import dataclass
from typing import IO, TextIO

logger = logging.getLogger(__name__)


from runtime_store.persist_paths import runtime_dir as persist_runtime_dir

def _runtime_dir() -> str:
    return persist_runtime_dir()


class SingleInstanceError(RuntimeError):
    """Eine andere Prozessinstanz hält bereits die Sperre."""


@dataclass(frozen=True)
class InstanceProbe:
    """Read-only snapshot of whether an instance lock is held."""

    name: str
    lock_path: str
    busy: bool
    pid: int | None


def is_pid_alive(pid: int) -> bool:
    """True if *pid* exists; PermissionError / access-denied counts as alive."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _is_pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_pid_alive_windows(pid: int) -> bool:
    """OpenProcess-based liveness; os.kill(pid, 0) is unreliable on Win/Py3.14+."""
    import ctypes

    # PROCESS_QUERY_LIMITED_INFORMATION
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    # ERROR_ACCESS_DENIED (5) → process exists but we cannot query it
    return ctypes.windll.kernel32.GetLastError() == 5


def lock_path_for(name: str) -> str:
    if not name.strip():
        raise ValueError("name darf nicht leer sein")
    return os.path.join(_runtime_dir(), f"{name}.lock")


def pid_path_for(name: str) -> str:
    if not name.strip():
        raise ValueError("name darf nicht leer sein")
    return os.path.join(_runtime_dir(), f"{name}.pid")


def _read_pid_from_path(path: str) -> int | None:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read().strip()
            if raw.isdigit():
                return int(raw)
    except OSError:
        pass
    return None


def _write_pid_sidecar(name: str, pid: int) -> None:
    path = pid_path_for(name)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(str(pid))
        handle.flush()


def _remove_pid_sidecar(name: str) -> None:
    path = pid_path_for(name)
    try:
        os.remove(path)
    except OSError:
        pass


def probe_instance(name: str) -> InstanceProbe:
    """Check whether another process holds the named lock (does not keep it)."""
    path = lock_path_for(name)
    if not os.path.exists(path):
        return InstanceProbe(name=name, lock_path=path, busy=False, pid=None)

    try:
        lock_file = open(path, "a+", encoding="utf-8")
    except OSError:
        # On Windows a held msvcrt lock can deny open — treat as busy.
        pid = _read_pid_from_path(pid_path_for(name))
        return InstanceProbe(name=name, lock_path=path, busy=True, pid=pid)

    try:
        try:
            _acquire_file_lock(lock_file)
        except OSError:
            pid = _read_pid_from_path(pid_path_for(name))
            if pid is None:
                pid = _read_pid_from_lock(lock_file)
            return InstanceProbe(name=name, lock_path=path, busy=True, pid=pid)
        try:
            _release_file_lock(lock_file)
        except OSError:
            logger.debug("probe_instance: Lock-Freigabe fehlgeschlagen", exc_info=True)
        return InstanceProbe(name=name, lock_path=path, busy=False, pid=None)
    finally:
        try:
            lock_file.close()
        except OSError:
            pass


def _acquire_file_lock(lock_file: IO) -> None:
    if sys.platform == "win32":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_file_lock(lock_file: IO) -> None:
    if sys.platform == "win32":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_pid_from_lock(lock_file: TextIO) -> int | None:
    try:
        lock_file.seek(0)
        raw = lock_file.read().strip()
        if raw.isdigit():
            return int(raw)
    except (OSError, ValueError):
        pass
    return None


def _build_busy_message(name: str, lock_path: str, other_pid: int | None) -> str:
    msg = f"Eine andere Instanz von {name} läuft bereits"
    if other_pid is not None:
        msg += f" (PID {other_pid})"
    return f"{msg}. Lock-Datei: {lock_path}"


class SingleInstanceLock:
    """Exklusive Dateisperre für genau eine laufende Instanz."""

    def __init__(self, name: str) -> None:
        if not name.strip():
            raise ValueError("name darf nicht leer sein")
        self._name = name
        self._lock_path = os.path.join(_runtime_dir(), f"{name}.lock")
        self._lock_file: TextIO | None = None
        self._released = False

    @property
    def lock_path(self) -> str:
        return self._lock_path

    def acquire(self) -> None:
        if self._lock_file is not None:
            raise RuntimeError(f"Single-Instance-Sperre für {self._name} ist bereits aktiv")

        os.makedirs(_runtime_dir(), exist_ok=True)
        lock_file = open(self._lock_path, "a+", encoding="utf-8")
        try:
            _acquire_file_lock(lock_file)
        except OSError as exc:
            other_pid = _read_pid_from_lock(lock_file)
            lock_file.close()
            raise SingleInstanceError(
                _build_busy_message(self._name, self._lock_path, other_pid)
            ) from exc

        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        self._lock_file = lock_file
        _write_pid_sidecar(self._name, os.getpid())
        atexit.register(self.release)
        logger.info(
            "Single-Instance-Sperre aktiv (PID %s, %s)",
            os.getpid(),
            self._lock_path,
        )

    def release(self) -> None:
        if self._released or self._lock_file is None:
            return
        self._released = True
        lock_file = self._lock_file
        self._lock_file = None
        _remove_pid_sidecar(self._name)
        try:
            _release_file_lock(lock_file)
        except OSError:
            logger.debug("Freigabe der Single-Instance-Sperre fehlgeschlagen", exc_info=True)
        try:
            lock_file.close()
        except OSError:
            pass


def ensure_single_instance(name: str) -> SingleInstanceLock:
    """Sperre holen oder SingleInstanceError auslösen."""
    lock = SingleInstanceLock(name)
    lock.acquire()
    return lock
