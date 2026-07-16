"""Subprocess-Start für scripts/run_backtesting aus der Streamlit-UI."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Callable, TextIO

from data import profile_manager
from runtime_store.persist_paths import resolve_backtesting_log_dir
from scripts.run_backtesting import BACKTESTING_YEAR
from simulation.backtesting_progress import (
    clear_progress_dir,
    prepare_progress_dir,
    read_progress_file,
    read_progress_snapshot,
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
) -> int:
    """Parallele Tasks: Haupt-Referenz + Extra-Referenzen + optimierte Szenarien."""
    from simulation.engine import plan_per_scenario_reference_tasks

    _, _, extra_specs = plan_per_scenario_reference_tasks(
        scenarios,
        live_scenario_id=live_scenario_id,
    )
    return 1 + len(extra_specs) + len(scenarios)


def auto_backtesting_workers(parallel_task_count: int) -> int:
    """Parallele Worker für Referenz + Szenario-Simulationen (ein Kern reserviert)."""
    if parallel_task_count <= 1:
        return 1
    cpu_count = os.cpu_count() or 2
    available = max(1, cpu_count - 1)
    return min(parallel_task_count, available)


def suggest_test_month() -> int | None:
    """Monat für Testlauf: März wenn Daten vorhanden, sonst erster überlappender Monat."""
    lox_min, lox_max = profile_manager.get_cons_data_date_bounds()
    if lox_min is None or lox_max is None:
        return None
    year_start = date(BACKTESTING_YEAR, 1, 1)
    year_end = date(BACKTESTING_YEAR, 12, 31)
    if lox_max < year_start or lox_min > year_end:
        return None
    march_start = date(BACKTESTING_YEAR, 3, 1)
    march_end = date(BACKTESTING_YEAR, 3, 31)
    if lox_max >= march_start and lox_min <= march_end:
        return 3
    overlap_start = max(lox_min, year_start)
    return overlap_start.month


def _subprocess_env() -> dict[str, str]:
    """Kindprozess-Env: PYTHONPATH + offline + ohne Debugpy-Hooks (VS-Code-Launcher)."""
    root = str(project_root())
    env = os.environ.copy()
    env["ENERGY_OPTIMIZER_OFFLINE"] = "1"
    for key in list(env):
        if any(key.startswith(prefix) for prefix in _DEBUGPY_ENV_PREFIXES):
            del env[key]
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
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
    """Startet Backtesting offline; gibt (exit_code, kombiniertes stdout/stderr) zurück."""
    log_dir = default_backtesting_output_dir() if output_dir is None else output_dir
    script_path = backtesting_script_path()
    if not script_path.is_file():
        message = f"Backtesting-Skript fehlt: {script_path}"
        return 1, message

    if progress_file:
        prepare_progress_dir(progress_file)

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
    while proc.poll() is None:
        if progress_file and on_progress is not None:
            on_progress(read_progress_snapshot(progress_file))
        time.sleep(_PROGRESS_POLL_SEC)

    stdout_reader.join(timeout=5.0)
    output = "".join(stdout_chunks)
    exit_code = _normalize_exit_code(proc.returncode or 0, output)
    if progress_file:
        clear_progress_dir(progress_file)
    return exit_code, output
