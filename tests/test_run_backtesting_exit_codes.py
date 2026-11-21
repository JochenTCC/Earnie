"""Exit codes of ``scripts/run_backtesting.py`` as a process: an abort exits 2, not 0 or 1."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from simulation.run_exit_codes import EXIT_ABORTED, aborted_exit

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("code", ["Abbruch: Verbrauchsdaten veraltet", 1, 3])
def test_a_deliberate_stop_maps_to_exit_aborted(code, capsys) -> None:
    mapped = aborted_exit(SystemExit(code))
    assert mapped.code == EXIT_ABORTED
    if isinstance(code, str):
        assert code in capsys.readouterr().err


@pytest.mark.parametrize("code", [None, 0])
def test_a_normal_end_stays_a_normal_end(code) -> None:
    assert aborted_exit(SystemExit(code)).code == code


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.run_backtesting", *args],
        cwd=ROOT,
        env={**env, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_an_abort_in_main_exits_2_with_its_message() -> None:
    proc = _run(["--workers", "0"], dict(os.environ))
    assert proc.returncode == EXIT_ABORTED, proc.stdout + proc.stderr
    assert "--workers muss >= 1 sein." in proc.stderr


def test_a_config_that_does_not_load_exits_2(tmp_path) -> None:
    # Same exit as a pending migration or an invalid pack: load_config_or_exit at import time.
    (tmp_path / "config.json").write_text("{ not json", encoding="utf-8")
    env = dict(os.environ)
    env["EARNIE_CONFIG_PATH"] = str(tmp_path / "config.json")
    proc = _run(["--workers", "1"], env)
    assert proc.returncode == EXIT_ABORTED, proc.stdout + proc.stderr
    assert "Abbruch" in proc.stderr
