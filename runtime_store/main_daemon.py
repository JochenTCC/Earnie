"""Start/stop/restart of the main.py optimizer daemon (lock + PID based)."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from runtime_store.single_instance import (
    InstanceProbe,
    is_pid_alive,
    probe_instance,
)

logger = logging.getLogger(__name__)

MAIN_INSTANCE_NAME = "main"
_START_WAIT_SEC = 15.0
_STOP_WAIT_SEC = 10.0
_DEBUGPY_ENV_PREFIXES = (
    "DEBUGPY",
    "PYDEVD",
    "BUNDLED_DEBUGPY",
    "VSCODE_DEBUGPY",
)

DaemonState = Literal["running", "stopped", "unknown"]


class DaemonError(RuntimeError):
    """Lifecycle operation failed (already running, start failed, etc.)."""


@dataclass(frozen=True)
class DaemonStatus:
    state: DaemonState
    pid: int | None
    lock_path: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def python_executable() -> str:
    root = project_root()
    if sys.platform == "win32":
        venv_python = root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def _subprocess_env() -> dict[str, str]:
    root = str(project_root())
    env = os.environ.copy()
    for key in list(env):
        if any(key.startswith(prefix) for prefix in _DEBUGPY_ENV_PREFIXES):
            del env[key]
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    return env


def _status_from_probe(probe: InstanceProbe) -> DaemonStatus:
    if probe.busy:
        if probe.pid is not None and not is_pid_alive(probe.pid):
            return DaemonStatus("unknown", probe.pid, probe.lock_path)
        return DaemonStatus("running", probe.pid, probe.lock_path)
    if probe.pid is not None and is_pid_alive(probe.pid):
        return DaemonStatus("running", probe.pid, probe.lock_path)
    return DaemonStatus("stopped", None, probe.lock_path)


def status() -> DaemonStatus:
    """Return daemon state from main.lock and PID liveness."""
    return _status_from_probe(probe_instance(MAIN_INSTANCE_NAME))


def start(*, wait_sec: float = _START_WAIT_SEC) -> DaemonStatus:
    """Spawn ``python main.py`` if not already running."""
    current = status()
    if current.state == "running":
        pid_part = f" (PID {current.pid})" if current.pid is not None else ""
        raise DaemonError(f"main.py läuft bereits{pid_part}")

    main_py = project_root() / "main.py"
    if not main_py.is_file():
        raise DaemonError(f"main.py nicht gefunden: {main_py}")

    # Detach from the parent console/stdin. Under VS Code debugpy
    # (integratedTerminal), a console-sharing child can deliver
    # KeyboardInterrupt to the Streamlit parent right after spawn.
    popen_kwargs: dict = {
        "cwd": str(project_root()),
        "env": _subprocess_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        # CREATE_NO_WINDOW: no console inheritance (debugpy-safe).
        # CREATE_NEW_PROCESS_GROUP: Ctrl+C does not target the daemon.
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        popen_kwargs["start_new_session"] = True

    logger.info("Starte main.py …")
    proc = subprocess.Popen(
        [python_executable(), str(main_py)],
        **popen_kwargs,
    )

    deadline = time.monotonic() + max(0.5, wait_sec)
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise DaemonError(
                f"main.py beendete sich sofort (exit {proc.returncode})"
            )
        current = status()
        if current.state == "running":
            logger.info("main.py läuft (PID %s)", current.pid)
            return current
        time.sleep(0.15)

    current = status()
    if current.state == "running":
        return current
    if proc.poll() is not None:
        raise DaemonError(f"main.py beendete sich (exit {proc.returncode})")
    raise DaemonError(
        "main.py startete, aber die Single-Instance-Sperre wurde nicht "
        f"innerhalb von {wait_sec:.0f}s gesetzt"
    )


def _force_kill(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            check=False,
            capture_output=True,
        )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        logger.debug("SIGKILL für PID %s fehlgeschlagen", pid, exc_info=True)


def stop(*, timeout_sec: float = _STOP_WAIT_SEC) -> DaemonStatus:
    """Terminate the process holding main.lock (graceful, then force)."""
    current = status()
    if current.state == "stopped":
        return current
    pid = current.pid
    if pid is None:
        raise DaemonError(
            "main.py scheint zu laufen, aber die PID ist unbekannt "
            f"(Lock: {current.lock_path})"
        )

    logger.info("Stoppe main.py (PID %s) …", pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return status()
    except OSError as exc:
        raise DaemonError(f"Stoppen von PID {pid} fehlgeschlagen: {exc}") from exc

    deadline = time.monotonic() + max(0.5, timeout_sec)
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            break
        time.sleep(0.2)
    else:
        logger.warning("main.py PID %s reagiert nicht – erzwinge Beendigung", pid)
        _force_kill(pid)
        force_deadline = time.monotonic() + 2.0
        while time.monotonic() < force_deadline and is_pid_alive(pid):
            time.sleep(0.1)

    return status()


def restart(
    *,
    stop_timeout_sec: float = _STOP_WAIT_SEC,
    start_wait_sec: float = _START_WAIT_SEC,
) -> DaemonStatus:
    """Stop if running, then start."""
    current = status()
    if current.state != "stopped":
        stop(timeout_sec=stop_timeout_sec)
        # Brief pause so the OS releases the lock file handle
        time.sleep(0.4)
        after = status()
        if after.state == "running":
            raise DaemonError(
                f"main.py konnte nicht gestoppt werden (PID {after.pid})"
            )
    return start(wait_sec=start_wait_sec)


def maybe_auto_start() -> DaemonStatus | None:
    """
    Start main.py when EARNIE_AUTO_START_MAIN=1 and daemon is stopped.

    Returns the new status if a start was attempted, else None.
    """
    from runtime_store.env_vars import is_truthy

    if not is_truthy("AUTO_START_MAIN"):
        return None
    current = status()
    if current.state == "running":
        logger.info(
            "Auto-Start übersprungen: main.py läuft bereits (PID %s)",
            current.pid,
        )
        return None
    return start()
