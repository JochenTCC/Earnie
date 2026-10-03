"""Re-solve one sunrise SE window and print flex delivery vs profile_spec (Class B dig).

Example (local earnie_env, Class B anchor)::

    $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
    .venv\\Scripts\\python.exe -m scripts.diag_class_b_window --anchor 2025-10-14T07:00:00
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / "earnie_env"

os.environ.setdefault("EARNIE_OFFLINE", "1")
sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Class B: sunrise window flex delivered vs profile_spec."
    )
    parser.add_argument(
        "--anchor",
        type=str,
        default="2025-10-14T07:00:00",
        help="Window anchor ISO (default: 2025-10-14T07:00:00)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="live",
        help="Scenario id (default: live)",
    )
    parser.add_argument(
        "--env",
        type=str,
        default="",
        help="Earnie env root with config/ + runtime/ (default: ./earnie_env or EARNIE_ENV_PATH)",
    )
    parser.add_argument(
        "--horizon-mode",
        type=str,
        default="sunrise_window",
        help="Horizon mode (default: sunrise_window)",
    )
    return parser.parse_args()


def _apply_env(env_root: Path) -> None:
    env_root = env_root.resolve()
    os.environ["EARNIE_ENV_PATH"] = str(env_root)
    config_json = env_root / "config" / "config.json"
    if config_json.is_file():
        os.environ["EARNIE_CONFIG_PATH"] = str(config_json)
    runtime = env_root / "runtime"
    if runtime.is_dir():
        os.environ["EARNIE_RUNTIME_PATH"] = str(runtime)


def main() -> int:
    args = _parse_args()
    env_root = Path(args.env) if args.env else Path(
        os.environ.get("EARNIE_ENV_PATH") or DEFAULT_ENV
    )
    if not (env_root / "config" / "config.json").is_file():
        print(f"ERROR: no config at {env_root / 'config' / 'config.json'}", file=sys.stderr)
        return 2
    _apply_env(env_root)

    from runtime_store.config_load import load_config_or_exit

    load_config_or_exit()
    from simulation.backtesting_log import load_backtesting_log
    from simulation.backtesting_single_window import (
        initial_soc_for_anchor,
        simulate_window_snapshot,
    )
    from simulation.plausibility import validate_window_consumption
    from optimizer import _delivered_flex_kwh_from_rows

    runtime_dir = env_root / "runtime"
    meta, hourly = load_backtesting_log(str(runtime_dir.resolve()))
    anchor = pd.Timestamp(args.anchor).to_pydatetime()
    if not isinstance(anchor, datetime):
        anchor = datetime.fromisoformat(str(args.anchor))
    soc = initial_soc_for_anchor(anchor, args.scenario, hourly)
    print(f"env:       {env_root}")
    print(f"anchor:    {anchor.isoformat(sep='T')}")
    print(f"scenario:  {args.scenario}")
    print(f"horizon:   {args.horizon_mode}")
    print(f"initial_soc: {soc:.1f}%")

    snap = simulate_window_snapshot(
        anchor,
        args.scenario,
        meta,
        initial_soc=soc,
        horizon_mode=args.horizon_mode,
    )
    step_meta = snap["meta"]
    rows_full = snap.get("chart_rows_full") or []
    rows_book = snap.get("chart_rows_24h") or rows_full
    consumers = step_meta.get("_flexible_consumers") or []
    # Per-consumer from full horizon (EV foresight); plausibility uses book rows + stash.
    delivered = _delivered_flex_kwh_from_rows(
        rows_full or rows_book, flexible_consumers=consumers
    )
    spec = dict(step_meta.get("spec_flex_targets_kwh") or {})
    plaus = validate_window_consumption(rows_book, step_meta)

    print(f"\n{'consumer':20} {'spec':>8} {'delivered':>10} {'delta':>8}")
    for cid in sorted(spec):
        t = float(spec[cid])
        d = float(delivered.get(cid, 0.0))
        print(f"{cid:20} {t:8.3f} {d:10.3f} {d - t:8.3f}")
    print(
        f"{'TOTAL':20} {sum(float(v) for v in spec.values()):8.3f} "
        f"{sum(float(delivered.get(k, 0.0)) for k in spec):10.3f} "
        f"{sum(float(delivered.get(k, 0.0)) - float(v) for k, v in spec.items()):8.3f}"
    )
    print(
        f"\nplausibility ok={plaus.ok} flex_diff={plaus.flex_diff_kwh} "
        f"opt_flex={plaus.optimized_flex_kwh} ref_flex={plaus.historical_flex_kwh}"
    )
    print(f"stash plausibility_optimized_flex_kwh={step_meta.get('plausibility_optimized_flex_kwh')}")
    return 0 if plaus.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
