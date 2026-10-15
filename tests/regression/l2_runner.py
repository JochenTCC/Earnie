"""L2 backtest window via simulation engine + offline fixtures."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

import pandas as pd

from tests.fixtures.backtesting_fixtures import (
    FIXTURES_ROOT,
    build_synthetic_prices_df,
    fixture_path,
    fixture_scenario_params,
    load_fixture_cache,
)
from tests.regression.loader import RegressionCase

_ENV_KEYS = (
    "EARNIE_CONFIG_PATH",
    "EARNIE_BACKTESTING_SCENARIOS_PATH",
    "EARNIE_TARIFFS_PATH",
    "EARNIE_HOUSE_PROFILES_PATH",
    "EARNIE_OFFLINE",
)


@contextmanager
def activate_backtesting_fixture_env() -> Iterator[Any]:
    """Bind config to ``tests/fixtures/backtesting/`` without pytest monkeypatch."""
    import config as config_module
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    os.environ["EARNIE_CONFIG_PATH"] = str(fixture_path("config.json"))
    os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"] = str(
        fixture_path("backtesting_scenarios.json")
    )
    os.environ["EARNIE_TARIFFS_PATH"] = str(fixture_path("tariffs.json"))
    os.environ["EARNIE_HOUSE_PROFILES_PATH"] = str(fixture_path("house_profiles.json"))
    os.environ["EARNIE_OFFLINE"] = "1"
    config_module.reinit_config()
    # install_open_meteo_climate_mock needs monkeypatch; L2 uses synthetic prices CSV path
    # via fixture config — Open-Meteo is not required for price_source=csv.
    del install_open_meteo_climate_mock
    try:
        yield config_module
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config_module.reinit_config()


def run_l2(case: RegressionCase) -> dict[str, Any]:
    from simulation.engine import run_simulation

    window = case.meta["window"]
    start = pd.Timestamp(str(window["start"]))
    end = pd.Timestamp(str(window["end"]))
    if end < start:
        raise ValueError(f"case {case.id}: window.end before start")

    with activate_backtesting_fixture_env():
        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        prices = build_synthetic_prices_df(
            start - pd.Timedelta(days=1),
            end + pd.Timedelta(days=1),
        )
        # Inject a negative-price hour when requested (synthetic stress).
        if case.meta.get("inputs", {}).get("force_negative_price"):
            prices = prices.copy()
            mid = prices.index[len(prices.index) // 2]
            prices.loc[mid, "price_cent_kwh"] = -5.0
        df, plausibility, _cbc = run_simulation(
            start,
            end,
            scenario,
            prices,
            cache=cache,
            scenario_id=str(
                case.meta.get("inputs", {}).get("scenario_id") or "fixture_5kwh_fixed"
            ),
            initial_soc=float(case.meta.get("inputs", {}).get("initial_soc", 50.0)),
        )
    return metrics_from_l2_frame(df, plausibility)


def metrics_from_l2_frame(df: pd.DataFrame, plausibility: Any) -> dict[str, Any]:
    import_kwh = float(df["import_kwh"].fillna(0).sum()) if "import_kwh" in df else 0.0
    export_kwh = float(df["export_kwh"].fillna(0).sum()) if "export_kwh" in df else 0.0
    cost = float(df["sim_cost"].fillna(0).sum()) if "sim_cost" in df else 0.0
    batt = (
        float(df["batt_action_kw"].abs().fillna(0).sum()) * 0.25
        if "batt_action_kw" in df
        else 0.0
    )
    failed = list(getattr(plausibility, "failed", []) or [])
    return {
        "status_optimal": 1 if not failed else 0,
        "n_slots": int(len(df)),
        "cost_euro": cost,
        "import_kwh": import_kwh,
        "export_kwh": export_kwh,
        "battery_throughput_kwh": batt,
        "plausibility_failures": float(len(failed)),
        "plan_hash": None,
    }


def fixtures_root() -> Any:
    return FIXTURES_ROOT
