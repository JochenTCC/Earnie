"""Verhindert parallele Instanzen desselben Hintergrunddienstes."""
from __future__ import annotations

import atexit
import logging
import os
import sys
from typing import IO, TextIO

logger = logging.getLogger(__name__)


from runtime_store.env_vars import read_env_or

def _runtime_dir() -> str:
    return read_env_or("RUNTIME_DIR", "runtime")


class SingleInstanceError(RuntimeError):
    """Eine andere Prozessinstanz hält bereits die Sperre."""


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
