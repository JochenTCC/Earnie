# tests/conftest.py
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tests.fixtures.historical_fixtures import CONS_DATA_FILE, fixture_available

ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = ROOT / ".env"


def _has_runtime_cons_data() -> bool:
    return (ROOT / "cons_data_hourly.csv").is_file() or (
        ROOT / "runtime" / "cons_data_hourly.csv"
    ).is_file()


requires_historical_data = pytest.mark.skipif(
    not fixture_available(),
    reason=(
        "tests/fixtures/historical/cons_data_hourly.csv fehlt "
        "(python -m scripts.extract_historical_fixtures)"
    ),
)


requires_runtime_cons_data = pytest.mark.skipif(
    not _has_runtime_cons_data(),
    reason="runtime/cons_data_hourly.csv wird für Backtesting-Smoke-Tests benötigt",
)


@pytest.fixture(scope="module")
def historical_cons_data():
    """Pfad zur isolierten cons_data-Test-Fixture (unabhängig von runtime/)."""
    if not fixture_available():
        pytest.skip(
            "tests/fixtures/historical/cons_data_hourly.csv fehlt "
            "(python -m scripts.extract_historical_fixtures)"
        )
    return str(CONS_DATA_FILE)


def _load_dotenv_for_tests() -> None:
    if DOTENV_PATH.is_file():
        load_dotenv(DOTENV_PATH, override=False)


_load_dotenv_for_tests()


def _loxone_integration_enabled() -> bool:
    if os.getenv("ENERGY_OPTIMIZER_SKIP_LOXONE_INTEGRATION") == "1":
        return False
    if not (
        (ROOT / "config.json").is_file() or (ROOT / "config" / "config.json").is_file()
    ):
        return False
    _load_dotenv_for_tests()
    return all(
        str(os.getenv(key, "")).strip()
        for key in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS")
    )


requires_loxone = pytest.mark.skipif(
    not _loxone_integration_enabled(),
    reason=(
        "Loxone-Integration: .env mit LOXONE_IP/USER/PASS und config.json erforderlich "
        "(ENERGY_OPTIMIZER_SKIP_LOXONE_INTEGRATION=1 zum Überspringen)"
    ),
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_loxone: Integrationstest gegen echten Loxone-Miniserver",
    )
    config.addinivalue_line(
        "markers",
        "slow: Längerer Backtesting- oder MILP-Integrationslauf",
    )
