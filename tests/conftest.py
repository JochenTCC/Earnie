# tests/conftest.py
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tests.fixtures.historical_fixtures import CONS_DATA_FILE, fixture_available

ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATHS = (ROOT / "config" / ".env", ROOT / ".env")
DEFAULT_TEST_CONFIG_PATH = ROOT / "tests" / "fixtures" / "backtesting" / "config.json"
_USE_LIVE_CONFIG_ENV = "ENERGY_OPTIMIZER_TEST_USE_LIVE_CONFIG"


def _apply_default_test_config_env() -> None:
    """Fixture-Config erzwingen — unabhängig von lokaler .env/NAS-Pfad."""
    if os.getenv(_USE_LIVE_CONFIG_ENV) == "1":
        return
    os.environ["ENERGY_OPTIMIZER_CONFIG_PATH"] = str(DEFAULT_TEST_CONFIG_PATH)
    os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


_apply_default_test_config_env()


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
    for dotenv_path in DOTENV_PATHS:
        if dotenv_path.is_file():
            load_dotenv(dotenv_path, override=False)
            break
    _apply_default_test_config_env()


_load_dotenv_for_tests()

import config as _config_module

_config_module.reinit_config()


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_config():
    """Stellt sicher, dass CONFIG nach Session-Start auf der Fixture-Config basiert."""
    _apply_default_test_config_env()
    _config_module.reinit_config()


@pytest.fixture(autouse=True)
def _restore_default_test_config_after_test():
    """Nach jedem Test zurück auf Fixture-Config (tmp_path-Overrides aus Einzeltests)."""
    yield
    _apply_default_test_config_env()
    _config_module.reinit_config()


def _loxone_integration_enabled() -> bool:
    if os.getenv("ENERGY_OPTIMIZER_SKIP_LOXONE_INTEGRATION") == "1":
        return False
    if os.getenv(_USE_LIVE_CONFIG_ENV) != "1":
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
        "Loxone-Integration: ENERGY_OPTIMIZER_TEST_USE_LIVE_CONFIG=1, .env mit "
        "LOXONE_IP/USER/PASS und config.json erforderlich "
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
    config.addinivalue_line(
        "markers",
        "requires_live_config: bewusst NAS/Prod-config.json (ENERGY_OPTIMIZER_TEST_USE_LIVE_CONFIG=1)",
    )
