"""commit_hours from backtesting_scenarios.json."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from settings.scenarios import (
    DEFAULT_BACKTESTING_COMMIT_HOURS,
    get_backtesting_commit_hours,
)


def test_commit_hours_default_when_missing(tmp_path: Path):
    path = tmp_path / "backtesting_scenarios.json"
    path.write_text(json.dumps({"scenarios": []}), encoding="utf-8")
    assert get_backtesting_commit_hours(str(path)) == DEFAULT_BACKTESTING_COMMIT_HOURS


def test_commit_hours_reads_value(tmp_path: Path):
    path = tmp_path / "backtesting_scenarios.json"
    path.write_text(
        json.dumps({"commit_hours": 24, "scenarios": []}),
        encoding="utf-8",
    )
    assert get_backtesting_commit_hours(str(path)) == 24


def test_commit_hours_rejects_zero(tmp_path: Path):
    path = tmp_path / "backtesting_scenarios.json"
    path.write_text(
        json.dumps({"commit_hours": 0, "scenarios": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="commit_hours"):
        get_backtesting_commit_hours(str(path))
