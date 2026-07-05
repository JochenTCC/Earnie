"""Isolierte cons_data-Fixture für historische Integrationstests."""
from __future__ import annotations

from pathlib import Path

FIXTURES_ROOT = Path(__file__).resolve().parent / "historical"
CONS_DATA_FILE = FIXTURES_ROOT / "cons_data_hourly.csv"


def cons_data_file() -> Path:
    return CONS_DATA_FILE


def fixture_available() -> bool:
    return CONS_DATA_FILE.is_file()
