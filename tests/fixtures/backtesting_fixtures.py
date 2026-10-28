"""Hilfen für Backtesting-Tests mit versionierten Offline-Fixtures."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd

FIXTURES_ROOT = Path(__file__).resolve().parent / "backtesting"

# Kalendertage mit bekanntem Verhalten in cons_data.csv (siehe README).
LOW_EAUTO_DAY = date(2026, 6, 25)
HIGH_EAUTO_DAY = date(2026, 6, 23)
BASELOAD_EDGE_DAY = date(2024, 7, 4)
SOC_CHAIN_START_DAY = date(2026, 6, 24)
SOC_CHAIN_END_DAY = date(2026, 6, 25)


_FLEX_CONSUMERS_INSTALLED = False


def _fixture_config_bound() -> bool:
    bound = os.environ.get("EARNIE_CONFIG_PATH", "")
    return bool(bound) and Path(bound).resolve() == (FIXTURES_ROOT / "config.json").resolve()


def install_fixture_flex_consumers() -> None:
    """Hängt die Fixture-Verbraucher (``flex_consumers.json``) an die Flex-Liste.

    Die Fixture-Config hat keinen ``flexible_consumers``-Block mehr (Overlay
    entfernt); die Historical-/Loxone-Zielquellen dieser Verbraucher gibt es im
    Hausprofil nicht. Nur aktiv, solange ``EARNIE_CONFIG_PATH`` auf die Fixture-Config zeigt.
    """
    global _FLEX_CONSUMERS_INSTALLED
    if _FLEX_CONSUMERS_INSTALLED:
        return
    from settings import flexible_consumers as fc_settings

    original = fc_settings.load_flexible_consumers

    def load_with_fixture_consumers(resolved, *, optimizer_only=False):
        if _fixture_config_bound():
            extra = json.loads(
                (FIXTURES_ROOT / "flex_consumers.json").read_text(encoding="utf-8")
            )
            resolved = {
                **resolved,
                "_planning_flex_consumers": extra
                + list(resolved.get("_planning_flex_consumers") or []),
            }
        return original(resolved, optimizer_only=optimizer_only)

    fc_settings.load_flexible_consumers = load_with_fixture_consumers

    from data import cons_data_house_profile as cons_profile

    original_ids = cons_profile.expected_cons_data_consumer_ids

    def expected_ids_with_fixture_consumers():
        if _fixture_config_bound():
            extra = json.loads(
                (FIXTURES_ROOT / "flex_consumers.json").read_text(encoding="utf-8")
            )
            return [str(item["id"]) for item in extra]
        return original_ids()

    cons_profile.expected_cons_data_consumer_ids = expected_ids_with_fixture_consumers
    _FLEX_CONSUMERS_INSTALLED = True


# Config and sidecar paths bound to the committed fixtures (pytest, regression runner).
FIXTURE_CONFIG_ENV = {
    "EARNIE_CONFIG_PATH": "config.json",
    "EARNIE_TARIFFS_PATH": "tariffs.json",
    "EARNIE_HOUSE_PROFILES_PATH": "house_profiles.json",
    "EARNIE_BACKTESTING_SCENARIOS_PATH": "backtesting_scenarios.json",
    "EARNIE_COMPONENTS_PATH": "components.json",
}


def pin_fixture_config_env() -> None:
    """Bind config and sidecars to ``FIXTURES_ROOT``, overriding any local site config.

    Force-overwrite (not setdefault): a shell, ``.env`` or a previous test must not leave
    a sidecar path behind.
    """
    for key, name in FIXTURE_CONFIG_ENV.items():
        os.environ[key] = str(FIXTURES_ROOT / name)
    os.environ.pop("EARNIE_DEVIATION_RULES_PATH", None)


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
        "EARNIE_CONFIG_PATH": os.environ.get("EARNIE_CONFIG_PATH"),
        "EARNIE_BACKTESTING_SCENARIOS_PATH": os.environ.get(
            "EARNIE_BACKTESTING_SCENARIOS_PATH"
        ),
        "EARNIE_TARIFFS_PATH": os.environ.get("EARNIE_TARIFFS_PATH"),
        "EARNIE_HOUSE_PROFILES_PATH": os.environ.get(
            "EARNIE_HOUSE_PROFILES_PATH"
        ),
        "EARNIE_OFFLINE": os.environ.get("EARNIE_OFFLINE"),
    }
    monkeypatch.setenv(
        "EARNIE_CONFIG_PATH",
        str(fixture_path("config.json")),
    )
    monkeypatch.setenv(
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        str(fixture_path("backtesting_scenarios.json")),
    )
    monkeypatch.setenv(
        "EARNIE_TARIFFS_PATH",
        str(fixture_path("tariffs.json")),
    )
    monkeypatch.setenv(
        "EARNIE_HOUSE_PROFILES_PATH",
        str(fixture_path("house_profiles.json")),
    )
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    config_module.reinit_config()
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
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


def fixture_tariff_params(
    import_tariff_id: str,
    export_tariff_id: str,
    *,
    timezone_name: str = "Europe/Vienna",
) -> dict:
    """Tariff part of resolved scenario params for hand-built scenarios (Edibert P3b).

    ``_edibert_pricing`` plus ``_import_tariff_spec`` / ``_export_tariff_spec`` / ``k_push_cent``
    from the fixture ``tariffs.json``, exactly as the scenario resolution attaches them (no house
    profile, so no grid fee).
    """
    from house_config.scenario_resolution import _attach_tariffs

    out: dict = {"timezone_name": timezone_name}
    _attach_tariffs(
        out,
        tariffs_path=str(fixture_path("tariffs.json")),
        grid_fees_path=str(fixture_path("grid_fees.json")),
        import_tariff_id=import_tariff_id,
        export_tariff_id=export_tariff_id,
        user_cents={},
        profile=None,
    )
    out.pop("timezone_name")
    return out
