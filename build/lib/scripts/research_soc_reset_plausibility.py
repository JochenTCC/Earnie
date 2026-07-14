"""Research: plausibility per window with fresh initial_soc (no carry-over)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "greenfield/runtime/backtesting_log.json"
CONFIG_DIR = ROOT / "greenfield/config"
RUNTIME_DIR = ROOT / "greenfield/runtime"

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")
os.environ["EARNIE_CONFIG_PATH"] = str(CONFIG_DIR / "config.json")
os.environ["EARNIE_RUNTIME_DIR"] = str(RUNTIME_DIR)
for suffix, name in (
    ("COMPONENTS_PATH", "components.json"),
    ("HOUSE_PROFILES_PATH", "house_profiles.json"),
    ("TARIFFS_PATH", "tariffs.json"),
    ("BACKTESTING_SCENARIOS_PATH", "backtesting_scenarios.json"),
):
    p = CONFIG_DIR / name
    if p.is_file():
        os.environ[f"EARNIE_{suffix}"] = str(p)

sys.path.insert(0, str(ROOT))

from runtime_store.config_load import load_config_or_exit  # noqa: E402

config = load_config_or_exit()
from data.data_loader import load_market_prices  # noqa: E402
from optimizer.simulation import delivered_flex_kwh_from_rows, simulate_horizon  # noqa: E402
from scripts.run_backtesting import resolve_backtesting_window  # noqa: E402
from simulation.backtesting_log import load_backtesting_log  # noqa: E402
from simulation.engine import (  # noqa: E402
    HistoricalDataCache,
    _flexible_consumers_from_scenario,
    _scenario_to_battery_params,
    build_historical_window_matrix,
    list_simulation_anchors,
    validate_window_consumption,
)

SCENARIO_ID = "s2-kein-pv"
RESET_SOC = 50.0
START_MONTH = pd.Timestamp(2025, 1, 1)
END_MONTH = pd.Timestamp(2025, 1, 31)

meta_log, _ = load_backtesting_log(str(RUNTIME_DIR))
stored_failures = {
    f["window_end"]
    for f in meta_log.get("plausibility", {}).get(SCENARIO_ID, {}).get("failures", [])
}

scenarios = config.get_backtesting_scenarios()
if SCENARIO_ID not in scenarios:
    raise SystemExit(f"Scenario {SCENARIO_ID} not in config")
scenario_params = dict(scenarios[SCENARIO_ID])

sim_cfg = config.get_file_paths_battery_simulation()
start, end = resolve_backtesting_window(
    START_MONTH,
    END_MONTH,
    sim_cfg.get("price_range", "last_12_months"),
    sim_cfg["path_consumption"],
    sim_cfg["path_production"],
)
cache = HistoricalDataCache()
cache.load()
anchors = list_simulation_anchors(start, end, cache)
prices_df = load_market_prices(
    start,
    end,
    sim_cfg,
    awattar_url=config.get("AWATTAR_URL"),
    timeout=config.get_global_timeout(default=30),
)
feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
battery_params = _scenario_to_battery_params(scenario_params)
flexible_consumers = _flexible_consumers_from_scenario(scenario_params)

results = []
for anchor in anchors:
    matrix, meta = build_historical_window_matrix(
        anchor,
        cache,
        prices_df,
        feed_in_settings=feed_in,
        scenario_params=scenario_params,
    )
    chart_rows = simulate_horizon(
        matrix,
        RESET_SOC,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        flexible_consumers=flexible_consumers,
    )
    plaus = validate_window_consumption(chart_rows, meta)
    delivered = delivered_flex_kwh_from_rows(chart_rows, flexible_consumers=flexible_consumers)
    window_end = pd.Timestamp(meta["window_end"]).isoformat()
    results.append(
        {
            "window_end": window_end,
            "ok": plaus.ok,
            "diff_kwh": plaus.diff_kwh,
            "flex_diff_kwh": plaus.flex_diff_kwh,
            "was_stored_failure": window_end in stored_failures,
            "delivered_flex": delivered,
            "targets": dict(meta["consumer_daily_targets_kwh"]),
            "end_soc": float(chart_rows[-1]["Simulierter SoC (%)"]),
        }
    )

failed = [r for r in results if not r["ok"]]
ok_count = len(results) - len(failed)
print(f"\n=== s2-kein-pv Jan 2025: independent windows, initial_soc={RESET_SOC}% ===")
print(f"Plausibility: {ok_count}/{len(results)} OK, {len(failed)} failed")
print(f"Stored sequential run: {meta_log['plausibility'][SCENARIO_ID]['ok_count']}/"
      f"{meta_log['plausibility'][SCENARIO_ID]['total_windows']} OK")

if failed:
    print("\n--- Still failing with SOC reset ---")
    for r in failed:
        print(f"  {r['window_end']}  flex_d={r['flex_diff_kwh']:.3f}  "
              f"was_seq_fail={r['was_stored_failure']}  end_soc={r['end_soc']:.1f}")
        for cid, target in r["targets"].items():
            got = r["delivered_flex"].get(cid, 0.0)
            if abs(got - target) > 0.01:
                print(f"    {cid}: target={target:.3f} delivered={got:.3f} "
                      f"delta={got - target:+.3f}")

recovered = [r for r in results if r["ok"] and r["was_stored_failure"]]
if recovered:
    print("\n--- Recovered with SOC reset (failed in sequential run) ---")
    for r in recovered:
        print(f"  {r['window_end']}")

still_seq_only = [
    r["window_end"]
    for r in results
    if r["ok"] and not r["was_stored_failure"]
]
print("\n--- Summary ---")
print(f"  Structural failures (fail even with SOC reset): {len(failed)}")
print(f"  SOC-carry-over only (seq fail, reset OK): {len(recovered)}")
print(f"  Names: structural={[r['window_end'][:10] for r in failed]}")
print(f"         recovered={[r['window_end'][:10] for r in recovered]}")

out = RUNTIME_DIR / "plausibility_soc_reset_research.json"
out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nWrote {out}")
