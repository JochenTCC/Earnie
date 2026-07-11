"""Unit tests for Greenfield Docker smoke helpers (no Docker required)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import smoke_greenfield_docker as smoke


def test_bootstrap_missing_paths_reports_gaps(tmp_path: Path):
    config_dir = tmp_path / "config"
    runtime_dir = tmp_path / "runtime"
    config_dir.mkdir()
    runtime_dir.mkdir()
    (config_dir / "config.json").write_text("{}", encoding="utf-8")

    missing = smoke.bootstrap_missing_paths(config_dir, runtime_dir)

    assert "config/.env" in missing
    assert "runtime/local_settings.json" in missing


def test_logs_indicate_healthy_worker_accepts_start_marker():
    ok, _ = smoke.logs_indicate_healthy_worker(
        "2026-07-11 INFO --- Earnie Live-Abfrage gestartet (v1.26.0) ---"
    )
    assert ok is True


def test_logs_indicate_healthy_worker_rejects_traceback():
    ok, detail = smoke.logs_indicate_healthy_worker(
        "Traceback (most recent call last):\n  File main.py"
    )
    assert ok is False
    assert "Traceback" in detail


def test_logs_indicate_healthy_worker_accepts_loxone_setup_wait():
    ok, _ = smoke.logs_indicate_healthy_worker(
        "Loxone-Zugangsdaten noch nicht hinterlegt (optional bis Live-/Silent-Betrieb)."
    )
    assert ok is True


def test_validate_greenfield_config_rejects_runtime_settings_block(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "config.json"
    path.write_text(
        json.dumps({"runtime_settings": {"battery_id": "b1", "pv_kwp": 10}}),
        encoding="utf-8",
    )
    ok, detail = smoke.validate_greenfield_config(path)
    assert ok is False
    assert "runtime_settings" in detail


def test_validate_greenfield_config_accepts_live_scenario(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "config.json"
    path.write_text(json.dumps({"live_scenario_id": "live"}), encoding="utf-8")
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "live",
                        "label": "Live",
                        "settings": {
                            "battery_id": "b1",
                            "import_tariff_id": "t1",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ok, _ = smoke.validate_greenfield_config(path)
    assert ok is True
