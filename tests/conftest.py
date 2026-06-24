# tests/conftest.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _has_runtime_data() -> bool:
    has_config = (ROOT / "config.json").is_file() or (ROOT / "config" / "config.json").is_file()
    has_cons_data = (ROOT / "cons_data_hourly.csv").is_file() or (
        ROOT / "runtime" / "cons_data_hourly.csv"
    ).is_file()
    return has_config and has_cons_data


requires_historical_data = pytest.mark.skipif(
    not _has_runtime_data(),
    reason="cons_data_hourly.csv und config.json werden für historische Tests benötigt",
)


def _loxone_integration_enabled() -> bool:
    if os.getenv("ENERGY_OPTIMIZER_RUN_LOXONE_INTEGRATION") != "1":
        return False
    if os.getenv("ENERGY_OPTIMIZER_OFFLINE") == "1":
        return False
    if not (
        (ROOT / "config.json").is_file() or (ROOT / "config" / "config.json").is_file()
    ):
        return False
    return all(
        str(os.getenv(key, "")).strip()
        for key in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS")
    )


requires_loxone = pytest.mark.skipif(
    not _loxone_integration_enabled(),
    reason=(
        "Setze ENERGY_OPTIMIZER_RUN_LOXONE_INTEGRATION=1 und LOXONE_IP/USER/PASS "
        "(ENERGY_OPTIMIZER_OFFLINE darf nicht 1 sein)"
    ),
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_loxone: Integrationstest gegen echten Loxone-Miniserver",
    )
