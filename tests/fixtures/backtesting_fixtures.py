"""Hilfen für Backtesting-Tests mit versionierten Offline-Fixtures."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd

FIXTURES_ROOT = Path(__file__).resolve().parent / "backtesting"

# Kalendertage mit bekanntem Verhalten in cons_data_hourly.csv (siehe README).
LOW_EAUTO_DAY = date(2026, 6, 25)
HIGH_EAUTO_DAY = date(2026, 6, 23)
BASELOAD_EDGE_DAY = date(2024, 7, 4)
SOC_CHAIN_START_DAY = date(2026, 6, 24)
SOC_CHAIN_END_DAY = date(2026, 6, 25)


def fixture_path(name: str) -> Path:
    path = FIXTURES_ROOT / name
    if not path.is_file():
        raise FileNotFoundError(f"Backtesting-Fixture fehlt: {path}")
    return path


def build_synthetic_prices_df(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    base_cent: float = 12.0,
    peak_hour: int = 18,
    peak_cent: float = 28.0,
) -> pd.DataFrame:
    """Stündliche EPEX-Preise (Cent/kWh) für Tests ohne API-Zugriff."""
    idx = pd.date_range(
        start.normalize(),
        end.normalize() + pd.Timedelta(days=1),
        freq="h",
    )
    prices = []
    for ts in idx:
        price = peak_cent if ts.hour == peak_hour else base_cent + (ts.hour % 4)
        prices.append(price)
    return pd.DataFrame({"price_cent_kwh": prices}, index=idx)


@contextmanager
def activate_backtesting_fixtures(monkeypatch):
    """
    Bindet Config und Backtesting-Szenarien an tests/fixtures/backtesting/.
    Ruft config.reinit_config() auf und stellt danach die Umgebung wieder her.
    """
    import config as config_module

    prev = {
        "ENERGY_OPTIMIZER_CONFIG_PATH": os.environ.get("ENERGY_OPTIMIZER_CONFIG_PATH"),
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH": os.environ.get(
            "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH"
        ),
        "ENERGY_OPTIMIZER_TARIFFS_PATH": os.environ.get("ENERGY_OPTIMIZER_TARIFFS_PATH"),
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH": os.environ.get(
            "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH"
        ),
        "ENERGY_OPTIMIZER_OFFLINE": os.environ.get("ENERGY_OPTIMIZER_OFFLINE"),
    }
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_CONFIG_PATH",
        str(fixture_path("config.json")),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        str(fixture_path("backtesting_scenarios.json")),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_TARIFFS_PATH",
        str(fixture_path("tariffs.json")),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(fixture_path("house_profiles.json")),
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_module.reinit_config()
    try:
        yield config_module
    finally:
        for key, value in prev.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        config_module.reinit_config()


def load_fixture_cache():
    """HistoricalDataCache mit Fixture-cons_data."""
    from simulation.engine import HistoricalDataCache

    cache = HistoricalDataCache()
    cache.load()
    return cache


def fixture_scenario_params() -> dict:
    """Erstes Szenario aus der Fixture-backtesting_scenarios.json."""
    import config

    scenarios = config.get_backtesting_scenarios()
    if "fixture_5kwh_fixed" not in scenarios:
        raise KeyError(
            "Fixture-Szenario 'fixture_5kwh_fixed' fehlt in backtesting_scenarios.json"
        )
    return dict(scenarios["fixture_5kwh_fixed"])
