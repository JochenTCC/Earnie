"""Tests für Remote-Backtesting-Konfiguration und SSH-Befehlsbau."""
from __future__ import annotations

import pytest

from scripts.remote_backtesting_support import (
    RemoteBacktestingError,
    _safe_join,
    _validated_configured_root,
    build_remote_run_command,
    result_share_dir,
    share_path,
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


def test_safe_join_rejects_parent_segments(tmp_path):
    with pytest.raises(RemoteBacktestingError, match="verlässt"):
        _safe_join(tmp_path, "../secret.txt")
    with pytest.raises(RemoteBacktestingError, match="verlässt"):
        _safe_join(tmp_path, "ok/../../secret.txt")


def test_safe_join_keeps_relative_child(tmp_path):
    target = _safe_join(tmp_path, "results/backtesting.csv")
    expected = tmp_path / "results" / "backtesting.csv"
    assert target == expected.resolve()


def test_validated_share_root_rejects_relative_and_controls(tmp_path):
    with pytest.raises(RemoteBacktestingError, match="absolut"):
        _validated_configured_root("relative/share", field="share_root")
    with pytest.raises(RemoteBacktestingError, match="Steuerzeichen"):
        _validated_configured_root(f"{tmp_path}\x00evil", field="share_root")
    root = _validated_configured_root(str(tmp_path), field="share_root")
    assert root == tmp_path.resolve()


def test_validated_share_root_accepts_unc_and_posix_cross_os():
    unc = _validated_configured_root(
        r"\\NAS\EnergyOptimizer\backtesting-sync", field="share_root"
    )
    assert str(unc) == r"\\NAS\EnergyOptimizer\backtesting-sync"
    posix = _validated_configured_root("/mnt/nas/backtesting-sync", field="share_root")
    assert str(posix).replace("\\", "/") == "/mnt/nas/backtesting-sync"


def test_result_share_dir_rejects_escape(tmp_path):
    cfg = _minimal_config()
    cfg["share_root"] = str(tmp_path)
    cfg["result_dir"] = "../outside"
    with pytest.raises(RemoteBacktestingError, match="result_dir"):
        result_share_dir(cfg)
    cfg["result_dir"] = "results"
    assert share_path(cfg) == tmp_path.resolve()
    assert result_share_dir(cfg) == tmp_path.resolve() / "results"


def test_build_remote_run_command_bash():
    cfg = _minimal_config()
    cfg["ssh"]["shell"] = "bash"
    cfg["remote_share_root"] = "/mnt/nas/backtesting-sync"
    cmd = build_remote_run_command(cfg, [])
    assert "rsync" in cmd
    assert "scripts.run_backtesting" in cmd
