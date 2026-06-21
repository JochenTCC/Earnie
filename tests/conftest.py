# tests/conftest.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _has_runtime_data() -> bool:
    return (ROOT / "cons_data_hourly.csv").is_file() and (ROOT / "config.json").is_file()


requires_historical_data = pytest.mark.skipif(
    not _has_runtime_data(),
    reason="cons_data_hourly.csv und config.json werden für historische Tests benötigt",
)
