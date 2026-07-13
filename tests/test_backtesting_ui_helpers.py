# tests/test_backtesting_ui_helpers.py
"""Tests für Backtesting-UI-Hilfsfunktionen (Stale-Erkennung, Config-Preflight)."""
from __future__ import annotations

import json
import os
from datetime import date

from scripts.run_backtesting import BACKTESTING_YEAR, _write_progress_file
from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW
from ui.backtesting import (
    horizon_selection_stale,
    log_horizon_mode,
    log_stale_reason,
    validate_backtesting_config,
)
from ui.backtesting_runner import (
    _normalize_exit_code,
    auto_backtesting_workers,
    backtesting_script_path,
    build_backtesting_command,
    default_backtesting_output_dir,
    read_progress_file,
    suggest_test_month,
)

def test_log_horizon_mode_from_period():
    assert log_horizon_mode({"period": {"horizon_mode": SUNRISE_WINDOW}}) == SUNRISE_WINDOW
    assert log_horizon_mode({"period": {}}) == FIXED_24H
    assert log_horizon_mode(None) is None


def test_horizon_selection_stale_when_ui_differs_from_log():
    meta = {"period": {"horizon_mode": SUNRISE_WINDOW}}
    assert horizon_selection_stale(meta, SUNRISE_WINDOW) is False
    assert horizon_selection_stale(meta, FIXED_24H) is True
    assert horizon_selection_stale(None, FIXED_24H) is False


def test_log_stale_reason_legacy_without_fingerprint():
    assert log_stale_reason({"period": {}}) == "legacy"


def test_log_stale_reason_none_when_fingerprint_matches(monkeypatch):
    meta = {"config_fingerprint": "abc123", "period": {"start": "2025-01-01"}}
    monkeypatch.setattr(
        "ui.backtesting.fingerprint_for_current_config",
        lambda *, period: "abc123",
    )
    assert log_stale_reason(meta) is None


def test_log_stale_reason_mismatch_when_fingerprint_differs(monkeypatch):
    meta = {"config_fingerprint": "old", "period": {}}
    monkeypatch.setattr(
        "ui.backtesting.fingerprint_for_current_config",
        lambda *, period: "new",
    )
    assert log_stale_reason(meta) == "mismatch"


def test_validate_backtesting_config_returns_error_on_resolution_failure(monkeypatch):
    def _fail():
        raise ValueError("Unbekannte export_tariff_id 'missing'.")

    monkeypatch.setattr("ui.backtesting.config.get_backtesting_scenarios", _fail)
    assert validate_backtesting_config() == "Unbekannte export_tariff_id 'missing'."


def test_normalize_exit_code_maps_module_error_despite_zero_returncode():
    output = "No module named scripts.run_backtesting\n"
    assert _normalize_exit_code(0, output) == 1


def test_backtesting_script_path_points_to_run_backtesting():
    path = backtesting_script_path()
    assert path.name == "run_backtesting.py"
    assert path.is_file()


def test_default_backtesting_output_dir_uses_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "gf-runtime"))
    assert default_backtesting_output_dir() == str(tmp_path / "gf-runtime")


def test_build_backtesting_command_includes_month_and_progress(tmp_path):
    cmd = build_backtesting_command(
        output_dir=str(tmp_path),
        start_month=6,
        end_month=6,
        progress_file=str(tmp_path / "progress.json"),
    )
    assert "--start-month" in cmd
    assert "6" in cmd
    assert "--progress-file" in cmd
    assert "--horizon-mode" not in cmd


def test_build_backtesting_command_includes_sunrise_horizon_mode(tmp_path):
    cmd = build_backtesting_command(
        output_dir=str(tmp_path),
        horizon_mode="sunrise_window",
    )
    assert cmd[-2:] == ["--horizon-mode", "sunrise_window"]


def test_auto_backtesting_workers_single_scenario():
    assert auto_backtesting_workers(0) == 1
    assert auto_backtesting_workers(1) == 1


def test_auto_backtesting_workers_caps_by_scenario_count(monkeypatch):
    monkeypatch.setattr("ui.backtesting_runner.os.cpu_count", lambda: 16)
    assert auto_backtesting_workers(4) == 4


def test_auto_backtesting_workers_reserves_one_core(monkeypatch):
    monkeypatch.setattr("ui.backtesting_runner.os.cpu_count", lambda: 8)
    assert auto_backtesting_workers(10) == 7


def test_build_backtesting_command_includes_workers_when_parallel(tmp_path):
    cmd = build_backtesting_command(output_dir=str(tmp_path), workers=4)
    assert "--workers" in cmd
    assert "4" in cmd


def test_build_backtesting_command_omits_workers_when_sequential(tmp_path):
    cmd = build_backtesting_command(output_dir=str(tmp_path), workers=1)
    assert "--workers" not in cmd


def test_suggest_test_month_from_cons_data_bounds(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_runner.profile_manager.get_cons_data_date_bounds",
        lambda: (date(2025, 3, 10), date(2025, 8, 1)),
    )
    assert suggest_test_month() == 3


def test_suggest_test_month_none_without_overlap(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_runner.profile_manager.get_cons_data_date_bounds",
        lambda: (date(2024, 1, 1), date(2024, 12, 31)),
    )
    assert suggest_test_month() is None


def test_write_and_read_progress_file(tmp_path):
    path = str(tmp_path / "progress.json")
    _write_progress_file(path, {"current": 3, "total": 10, "scenario": "Runtime", "phase": "simulation"})
    loaded = read_progress_file(path)
    assert loaded is not None
    assert loaded["current"] == 3
    assert loaded["scenario"] == "Runtime"


def test_write_progress_file_falls_back_on_windows_replace_error(monkeypatch, tmp_path):
    path = str(tmp_path / "progress.json")
    payload = {"current": 5, "total": 10, "scenario": "Runtime", "phase": "simulation"}
    replace_calls = {"count": 0}

    def _fail_replace(src, dst):
        replace_calls["count"] += 1
        raise PermissionError(13, "Zugriff verweigert", str(src), str(dst), 5)

    monkeypatch.setattr("scripts.run_backtesting.Path.replace", _fail_replace)
    _write_progress_file(path, payload)
    assert replace_calls["count"] == 3
    loaded = read_progress_file(path)
    assert loaded == payload


def test_run_backtesting_module_import_does_not_force_offline(monkeypatch):
    """Streamlit UI imports BACKTESTING_YEAR — must not pollute process env."""
    import importlib

    import scripts.run_backtesting as rb

    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    importlib.reload(rb)
    assert os.environ.get("ENERGY_OPTIMIZER_OFFLINE") is None
    assert os.environ.get("EARNIE_OFFLINE") is None
    assert BACKTESTING_YEAR == 2025
