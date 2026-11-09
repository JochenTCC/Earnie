"""Subprocess-Start für scripts/run_backtesting aus der Streamlit-UI."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TextIO

from runtime_store.persist_paths import resolve_backtesting_log_dir
from simulation.backtesting_progress import (
    clear_cancel_request,
    clear_progress_dir,
    read_progress_file,
    read_progress_snapshot,
    request_cancel,
)
from simulation.horizon_mode import DEFAULT_HORIZON_MODE

_FAILURE_MARKERS = (
    "No module named scripts.run_backtesting",
    "ModuleNotFoundError: No module named 'scripts'",
    "No module named scripts",
)
_DEBUGPY_ENV_PREFIXES = (
    "DEBUGPY",
    "PYDEVD",
    "BUNDLED_DEBUGPY",
    "VSCODE_DEBUGPY",
)
_PROGRESS_POLL_SEC = 0.5


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def backtesting_script_path() -> Path:
    return project_root() / "scripts" / "run_backtesting.py"


def python_executable() -> str:
    venv_python = project_root() / ".venv" / "Scripts" / "python.exe"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def default_backtesting_output_dir() -> str:
    return resolve_backtesting_log_dir()


def default_progress_file_path() -> str:
    return str(Path(default_backtesting_output_dir()) / ".backtesting_progress")


def count_backtesting_parallel_tasks(
    scenarios: dict[str, dict],
    *,
    live_scenario_id: str,
    own_reference_by_scenario: dict[str, bool | None] | None = None,
) -> int:
    """Parallele Tasks: Haupt-Referenz + L0-, L1-, L2-Referenzen + optimierte Szenarien."""
    from simulation.engine import plan_per_scenario_reference_tasks
    from simulation.reference_ladder import plan_ladder_reference_tasks

    flags = own_reference_by_scenario
    if flags is None:
        import config

        flags = config.get_own_reference_flags()
    _, _, extra_specs = plan_per_scenario_reference_tasks(
        scenarios,
        live_scenario_id=live_scenario_id,
        own_reference_by_scenario=flags,
    )
    _, ladder_specs = plan_ladder_reference_tasks(scenarios)
    return 1 + len(extra_specs) + len(ladder_specs) + len(scenarios)


def auto_backtesting_workers(parallel_task_count: int) -> int:
    """Parallele Worker für Referenz + Szenario-Simulationen (ein Kern reserviert)."""
    if parallel_task_count <= 1:
        return 1
    cpu_count = os.cpu_count() or 2
    available = max(1, cpu_count - 1)
    return min(parallel_task_count, available)


def suggest_test_month() -> int | None:
    """Monat für Testlauf: März im SE-Fenster, sonst erster Monat im Fenster."""
    from data.data_loader import resolve_simulation_window

    try:
        start, end = resolve_simulation_window()
    except ValueError:
        return None
    cursor = start.to_period("M")
    end_period = end.to_period("M")
    first_month: int | None = None
    while cursor <= end_period:
        month = int(cursor.month)
        if first_month is None:
            first_month = month
        if month == 3:
            return 3
        cursor += 1
    return first_month


_CLOUD_SESSION_PATH_OVERRIDE_SUFFIXES = (
    "ENV_PATH",
    "CONFIG_PATH",
    "RUNTIME_PATH",
    "RUNTIME_DIR",
    "BACKTESTING_SCENARIOS_PATH",
    "TARIFFS_PATH",
    "HOUSE_PROFILES_PATH",
    "COMPONENTS_PATH",
    "DEVIATION_RULES_PATH",
    "LOCAL_SETTINGS_PATH",
    "DOTENV_PATH",
)


def _apply_cloud_session_env(env: dict[str, str]) -> str | None:
    """Point SE subprocess at the Streamlit cloud-demo session workspace."""
    from runtime_store.cloud_demo import get_session_env_root

    session = get_session_env_root()
    if not session:
        return None
    for suffix in _CLOUD_SESSION_PATH_OVERRIDE_SUFFIXES:
        env.pop(f"EARNIE_{suffix}", None)
    env["EARNIE_ENV_PATH"] = session
    return session


def _subprocess_env() -> dict[str, str]:
    """Kindprozess-Env: PYTHONPATH + offline + ohne Debugpy-Hooks (VS-Code-Launcher)."""
    root = str(project_root())
    env = os.environ.copy()
    env["EARNIE_OFFLINE"] = "1"
    for key in list(env):
        if any(key.startswith(prefix) for prefix in _DEBUGPY_ENV_PREFIXES):
            del env[key]
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    _apply_cloud_session_env(env)
    return env


def _normalize_exit_code(returncode: int, output: str) -> int:
    if returncode != 0:
        return returncode
    if any(marker in output for marker in _FAILURE_MARKERS):
        return 1
    return returncode


def _drain_subprocess_stdout(pipe: TextIO | None, chunks: list[str]) -> None:
    """Liest stdout inkrementell, damit der Kindprozess nicht am Pipe-Puffer blockiert."""
    if pipe is None:
        return
    try:
        while True:
            data = pipe.read(4096)
            if not data:
                break
            chunks.append(data)
    finally:
        pipe.close()


def build_backtesting_command(
    *,
    output_dir: str,
    start_month: int | None = None,
    end_month: int | None = None,
    progress_file: str | None = None,
    horizon_mode: str = DEFAULT_HORIZON_MODE,
    workers: int = 1,
) -> list[str]:
    script_path = backtesting_script_path()
    cmd = [
        python_executable(),
        str(script_path),
        "--output-dir",
        output_dir,
    ]
    if start_month is not None:
        cmd.extend(["--start-month", str(start_month)])
    if end_month is not None:
        cmd.extend(["--end-month", str(end_month)])
    if progress_file:
        cmd.append("--progress-file")
        cmd.append(progress_file)
    if horizon_mode != DEFAULT_HORIZON_MODE:
        cmd.extend(["--horizon-mode", horizon_mode])
    if workers > 1:
        cmd.extend(["--workers", str(workers)])
    return cmd


@dataclass
class BacktestingRun:
    """A started SE subprocess. The UI keeps it in the session, so a rerun or a page change
    does not lose the run: the page attaches to it again and can still cancel it."""

    proc: subprocess.Popen
    output_chunks: list[str]
    reader: threading.Thread
    progress_file: str | None
    cancel_requested: bool = field(default=False)

    def running(self) -> bool:
        return self.proc.poll() is None


def start_backtesting_subprocess(
    *,
    output_dir: str | None = None,
    start_month: int | None = None,
    end_month: int | None = None,
    progress_file: str | None = None,
    horizon_mode: str = DEFAULT_HORIZON_MODE,
    workers: int = 1,
) -> BacktestingRun:
    """Start the SE subprocess and return at once. Raises ``FileNotFoundError`` without the script."""
    log_dir = default_backtesting_output_dir() if output_dir is None else output_dir
    script_path = backtesting_script_path()
    if not script_path.is_file():
        raise FileNotFoundError(f"Backtesting-Skript fehlt: {script_path}")
    # A marker left by an earlier cancel must not stop the new run.
    clear_cancel_request(progress_file)
    cmd = build_backtesting_command(
        output_dir=log_dir,
        start_month=start_month,
        end_month=end_month,
        progress_file=progress_file,
        horizon_mode=horizon_mode,
        workers=workers,
    )
    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root()),
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_chunks: list[str] = []
    stdout_reader = threading.Thread(
        target=_drain_subprocess_stdout,
        args=(proc.stdout, stdout_chunks),
        daemon=True,
    )
    stdout_reader.start()
    return BacktestingRun(
        proc=proc,
        output_chunks=stdout_chunks,
        reader=stdout_reader,
        progress_file=progress_file,
    )


def cancel_backtesting_run(run: BacktestingRun) -> None:
    """Ask the run to stop; its workers end at their next simulated hour (exit ``EXIT_CANCELLED``)."""
    if run.progress_file is None:
        raise ValueError("SE cancel needs the run's progress file")
    request_cancel(run.progress_file)
    run.cancel_requested = True


def finish_backtesting_run(run: BacktestingRun) -> tuple[int, str]:
    """Wait for the subprocess, return (exit_code, combined stdout/stderr), clear progress files."""
    run.proc.wait()
    run.reader.join(timeout=5.0)
    output = "".join(run.output_chunks)
    exit_code = _normalize_exit_code(run.proc.returncode or 0, output)
    if run.progress_file:
        clear_progress_dir(run.progress_file)
    return exit_code, output


def poll_backtesting_progress(
    run: BacktestingRun,
    on_progress: Callable[[dict[str, dict]], None] | None = None,
) -> None:
    """Report progress until the subprocess ends."""
    while run.running():
        if run.progress_file and on_progress is not None:
            on_progress(read_progress_snapshot(run.progress_file))
        time.sleep(_PROGRESS_POLL_SEC)


def run_backtesting_subprocess(
    *,
    output_dir: str | None = None,
    start_month: int | None = None,
    end_month: int | None = None,
    progress_file: str | None = None,
    horizon_mode: str = DEFAULT_HORIZON_MODE,
    workers: int = 1,
    on_progress: Callable[[dict[str, dict]], None] | None = None,
) -> tuple[int, str]:
    """Startet Backtesting offline und wartet; gibt (exit_code, kombiniertes stdout/stderr) zurück."""
    try:
        run = start_backtesting_subprocess(
            output_dir=output_dir,
            start_month=start_month,
            end_month=end_month,
            progress_file=progress_file,
            horizon_mode=horizon_mode,
            workers=workers,
        )
    except FileNotFoundError as exc:
        return 1, str(exc)
    poll_backtesting_progress(run, on_progress)
    return finish_backtesting_run(run)
