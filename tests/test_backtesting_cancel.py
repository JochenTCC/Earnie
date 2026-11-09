"""Cancelling a Szenario-Explorer run: marker file, worker check, subprocess runner."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from simulation import backtesting_progress as bp
from ui import backtesting_runner as runner


@pytest.fixture
def progress_dir(tmp_path) -> str:
    return str(tmp_path / ".backtesting_progress")


def test_cancel_marker_round_trip(progress_dir):
    assert bp.cancel_requested(progress_dir) is False
    bp.request_cancel(progress_dir)
    assert bp.cancel_requested(progress_dir) is True
    worker = bp.worker_progress_path(progress_dir, "live")
    assert bp.worker_cancel_requested(worker) is True
    bp.clear_cancel_request(progress_dir)
    assert bp.cancel_requested(progress_dir) is False
    assert bp.worker_cancel_requested(worker) is False


def test_prepare_keeps_an_early_cancel_and_clear_removes_it(progress_dir):
    bp.request_cancel(progress_dir)
    bp.prepare_progress_dir(progress_dir)
    assert bp.cancel_requested(progress_dir) is True
    bp.clear_progress_dir(progress_dir)
    assert bp.cancel_requested(progress_dir) is False


def test_request_cancel_without_progress_path_fails_loud():
    with pytest.raises(ValueError):
        bp.request_cancel(None)


def test_progress_printer_stops_the_worker_at_the_next_hour(progress_dir):
    from scripts.run_backtesting import _make_progress_printer

    bp.prepare_progress_dir(progress_dir)
    printer = _make_progress_printer("Live", bp.worker_progress_path(progress_dir, "live"))
    printer(1, 10)
    bp.request_cancel(progress_dir)
    with pytest.raises(bp.BacktestingCancelled):
        printer(2, 10)


def _fake_command(monkeypatch, code: str) -> None:
    monkeypatch.setattr(
        runner,
        "build_backtesting_command",
        lambda **_kwargs: [sys.executable, "-c", code],
    )


def test_cancelled_subprocess_ends_with_the_cancel_exit_code(progress_dir, monkeypatch):
    marker = Path(progress_dir) / bp.CANCEL_MARKER_NAME
    # Stands in for run_backtesting: waits for the marker like its workers, then exits 130.
    code = (
        "import os, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "for _ in range(600):\n"
        "    if os.path.exists(marker):\n"
        "        print('abgebrochen'); sys.exit(130)\n"
        "    time.sleep(0.05)\n"
        "sys.exit(1)\n"
    )
    _fake_command(monkeypatch, code)
    run = runner.start_backtesting_subprocess(progress_file=progress_dir, output_dir=progress_dir)
    assert run.running()
    runner.cancel_backtesting_run(run)
    assert run.cancel_requested is True
    exit_code, output = runner.finish_backtesting_run(run)
    assert exit_code == bp.EXIT_CANCELLED
    assert "abgebrochen" in output
    assert not marker.exists()


def test_start_clears_a_stale_cancel_marker(progress_dir, monkeypatch):
    bp.request_cancel(progress_dir)
    marker = Path(progress_dir) / bp.CANCEL_MARKER_NAME
    _fake_command(monkeypatch, f"import os, sys; sys.exit(130 if os.path.exists({str(marker)!r}) else 0)")
    run = runner.start_backtesting_subprocess(progress_file=progress_dir, output_dir=progress_dir)
    assert runner.finish_backtesting_run(run) == (0, "")


def test_run_backtesting_subprocess_still_blocks_and_reports(progress_dir, monkeypatch):
    _fake_command(monkeypatch, "print('fertig')")
    seen: list[dict] = []
    exit_code, output = runner.run_backtesting_subprocess(
        progress_file=progress_dir, output_dir=progress_dir, on_progress=seen.append
    )
    assert exit_code == 0
    assert "fertig" in output


def test_parallel_run_stops_with_cancelled_not_a_failure(monkeypatch):
    """A cancelled worker ends the pool and the run as cancelled, not as a failed scenario."""
    from concurrent.futures import ThreadPoolExecutor

    import pandas as pd

    from scripts import run_backtesting as rb

    def _worker(name, *_args, **_kwargs):
        raise bp.BacktestingCancelled(f"{name}: abgebrochen")

    monkeypatch.setattr(rb, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(rb, "_run_scenario_worker", _worker)
    with pytest.raises(bp.BacktestingCancelled):
        rb._run_parallel_backtesting(
            [],
            {"a": {}, "b": {}},
            {},
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-01-31"),
            None,
            2,
            "sunrise_window",
            "perfect",
            None,
            None,
            progress_file=None,
            ladder_specs=[],
        )
