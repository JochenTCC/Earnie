"""Subprocess-Start für scripts/run_backtesting aus der Streamlit-UI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def python_executable() -> str:
    venv_python = project_root() / ".venv" / "Scripts" / "python.exe"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def run_backtesting_subprocess(*, output_dir: str = ".") -> tuple[int, str]:
    """Startet Backtesting offline; gibt (exit_code, kombiniertes stdout/stderr) zurück."""
    cmd = [
        python_executable(),
        "-m",
        "scripts.run_backtesting",
        "--output-dir",
        output_dir,
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(project_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output
