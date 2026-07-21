"""Reproduce May 14 2026 EV under-delivery (greenfield live, chained SOC)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")
os.environ["EARNIE_ENV_PATH"] = str(ROOT / "greenfield")
os.environ["EARNIE_CONFIG_PATH"] = str(ROOT / "greenfield/config")
os.environ["EARNIE_RUNTIME_PATH"] = str(ROOT / "greenfield/runtime")
for env_key, name in (
    ("EARNIE_COMPONENTS_PATH", "components.json"),
    ("EARNIE_HOUSE_PROFILES_PATH", "house_profiles.json"),
    ("EARNIE_TARIFFS_PATH", "tariffs.json"),
    ("EARNIE_BACKTESTING_SCENARIOS_PATH", "backtesting_scenarios.json"),
):
    path = ROOT / "greenfield/config" / name
    if path.is_file():
        os.environ[env_key] = str(path)

sys.path.insert(0, str(ROOT))

import pandas as pd

from data.data_loader import load_market_prices
from optimizer.simulation import delivered_flex_kwh_from_rows, simulate_horizon
from runtime_store.config_load import load_config_or_exit
from scripts.run_backtesting import resolve_backtesting_window
from simulation.engine import (
    HistoricalDataCache,
    _flexible_consumers_from_scenario,
    _scenario_to_battery_params,
    _simulate_anchor_step,
    list_simulation_anchors,
    validate_window_consumption,
)
from simulation.horizon_mode import FIXED_24H

TARGET = pd.Timestamp("2026-05-14 07:00:00")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce May 14 2026 EV window.")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Only simulate the May 14 window at 11.6%% SOC (no full chain).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = load_config_or_exit()
    params = dict(config.get_backtesting_scenarios()["live"])
    sim_cfg = config.get_scenario_explorer_conf()
    start, end = resolve_backtesting_window(
        pd.Timestamp("2025-07-14"),
        pd.Timestamp("2026-07-14"),
        sim_cfg.get("price_range", "last_12_months"),
    )
    cache = HistoricalDataCache()
    cache.load()
    anchors = list_simulation_anchors(start, end, cache)
    idx = next(i for i, a in enumerate(anchors) if pd.Timestamp(a) == TARGET)

    prices = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )
    battery = _scenario_to_battery_params(params)
    feed_in = config.get_backtesting_feed_in_settings(runtime_override=params)

    sim_soc = 50.0 if not args.quick else 11.6
    if args.quick:
        start_idx = idx
    else:
        start_idx = 0
    for i in range(start_idx, idx + 1):
        chart, matrix, meta, sim_soc, *_ = _simulate_anchor_step(
            anchor=anchors[i],
            sim_soc=sim_soc,
            horizon_mode=FIXED_24H,
            cache=cache,
            prices_df=prices,
            scenario_params=params,
            battery_params=battery,
            feed_in_settings=feed_in,
            hours_done=i * 24,
            collect_cbc=False,
            collect_full_horizon=False,
        )

    result = validate_window_consumption(chart, meta)
    delivered = delivered_flex_kwh_from_rows(chart, flexible_consumers=_flexible_consumers_from_scenario(params))
    print(f"plausibility_ok={result.ok} diff_kwh={result.diff_kwh:.3f}")
    print(f"ev_delivered={delivered.get('ev', 0):.3f} target={meta['consumer_daily_targets_kwh'].get('ev', 0)}")


if __name__ == "__main__":
    main()
