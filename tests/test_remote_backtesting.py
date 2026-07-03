"""Tests für Remote-Backtesting-Konfiguration und SSH-Befehlsbau."""
from __future__ import annotations

import pytest

from scripts.remote_backtesting_support import (
    RemoteBacktestingError,
    build_remote_run_command,
    validate_remote_config,
)


def _minimal_config() -> dict:
    return {
        "share_root": r"\\NAS\EnergyOptimizer\backtesting-sync",
        "remote_share_root": r"\\NAS\EnergyOptimizer\backtesting-sync",
        "sync_paths": ["config/config.json"],
        "result_dir": "results",
        "result_files": ["backtesting_log.json"],
        "ssh": {
            "host": "192.168.1.10",
            "user": "test",
            "remote_repo": "C:/Energy-Optimizer",
            "python": "python",
            "shell": "powershell",
        },
    }


def test_validate_remote_config_ok():
    assert validate_remote_config(_minimal_config())["share_root"]


def test_validate_remote_config_missing_share():
    cfg = _minimal_config()
    cfg.pop("share_root")
    with pytest.raises(RemoteBacktestingError, match="share_root"):
        validate_remote_config(cfg)


def test_build_remote_run_command_powershell():
    cmd = build_remote_run_command(_minimal_config(), ["--start-month", "6"])
    assert "scripts.run_backtesting" in cmd
    assert "--start-month 6" in cmd
    assert "robocopy" in cmd


def test_build_remote_run_command_bash():
    cfg = _minimal_config()
    cfg["ssh"]["shell"] = "bash"
    cfg["remote_share_root"] = "/mnt/nas/backtesting-sync"
    cmd = build_remote_run_command(cfg, [])
    assert "rsync" in cmd
    assert "scripts.run_backtesting" in cmd
