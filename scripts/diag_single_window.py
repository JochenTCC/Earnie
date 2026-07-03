"""Diagnose: einzelnes Backtesting-Fenster gezielt ausführen und timen."""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

import pandas as pd

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

import config
from data.data_loader import load_market_prices
from optimizer.charging_context import resolve_charging_context
from optimizer.milp import milp_optimizer
from optimizer.simulation import simulate_horizon
from scripts.run_backtesting import resolve_backtesting_window
from simulation.engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    build_historical_window_matrix,
    list_simulation_anchors,
    window_slot_datetimes,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Einzelnes Backtesting-Fenster diagnostizieren.")
    parser.add_argument(
        "--hour-offset",
        type=int,
        help="Stunden-Fortschritt wie in run_backtesting (z. B. 1392)",
    )
    parser.add_argument(
        "--anchor",
        type=str,
        help="Ankerzeitpunkt ISO (z. B. 2025-09-28 07:00:00)",
    )
    parser.add_argument(
        "--start-month",
        type=int,
        default=8,
        help="Startmonat für Fensterliste (Standard: 8)",
    )
    parser.add_argument(
        "--end-month",
        type=int,
        default=9,
        help="Endmonat für Fensterliste (Standard: 9)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="runtime_settings",
        help="Szenario-ID aus backtesting_scenarios / runtime_settings",
    )
    parser.add_argument(
        "--initial-soc",
        type=float,
        default=50.0,
        help="Start-SOC für simulate_horizon",
    )
    parser.add_argument(
        "--milp-only",
        action="store_true",
        help="Nur ersten MILP-Aufruf (Stunde 0) timen",
    )
    return parser.parse_args()


def _load_anchor_by_hour_offset(
    hour_offset: int,
    start_month: int,
    end_month: int,
) -> tuple[datetime, int, list[datetime]]:
    sim_cfg = config.get_file_paths_battery_simulation()
    start, end = resolve_backtesting_window(
        pd.Timestamp(2025, start_month, 1),
        pd.Timestamp(2025, end_month, 1),
        sim_cfg.get("price_range", "last_12_months"),
        sim_cfg["path_consumption"],
        sim_cfg["path_production"],
    )
    cache = HistoricalDataCache()
    cache.load()
    anchors = list_simulation_anchors(start, end, cache)
    win_idx = hour_offset // 24
    if win_idx < 0 or win_idx >= len(anchors):
        raise SystemExit(
            f"hour-offset {hour_offset} liegt ausserhalb "
            f"(0..{len(anchors) * 24 - 1}, {len(anchors)} Fenster)."
        )
    return anchors[win_idx], win_idx, anchors


def _scenario_params(scenario_id: str) -> dict:
    scenarios = config.get_backtesting_scenarios()
    if scenario_id not in scenarios:
        raise SystemExit(f"Szenario '{scenario_id}' nicht gefunden: {sorted(scenarios)}")
    return dict(scenarios[scenario_id])


def _print_window_stats(anchor: datetime, cache: HistoricalDataCache) -> dict:
    slots = window_slot_datetimes(anchor)
    _, totals, total_load, _ = cache.get_window_consumption(slots)
    print(f"Anker:     {anchor}")
    print(f"Fenster:   {slots[0]} -> {slots[-1]}")
    print(f"Verbrauch: gesamt={sum(total_load):.2f} kWh, baseload inkl.")
    for cid, kwh in sorted(totals.items()):
        print(f"  {cid}: {kwh:.3f} kWh")
    return dict(totals)


def main() -> None:
    args = _parse_args()
    scenario_params = _scenario_params(args.scenario)

    if args.anchor:
        anchor = pd.Timestamp(args.anchor).to_pydatetime()
        win_idx = None
        anchors = []
    elif args.hour_offset is not None:
        anchor, win_idx, anchors = _load_anchor_by_hour_offset(
            args.hour_offset, args.start_month, args.end_month
        )
        print(
            f"Fortschritt {args.hour_offset}/{len(anchors) * 24} h "
            f"-> Fenster-Index {win_idx} (1-basiert: {win_idx + 1})"
        )
    else:
        raise SystemExit("Bitte --hour-offset oder --anchor angeben.")

    sim_cfg = config.get_file_paths_battery_simulation()
    start, end = resolve_backtesting_window(
        pd.Timestamp(2025, args.start_month, 1),
        pd.Timestamp(2025, args.end_month, 1),
        sim_cfg.get("price_range", "last_12_months"),
        sim_cfg["path_consumption"],
        sim_cfg["path_production"],
    )
    prices = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )

    cache = HistoricalDataCache()
    cache.load()
    feed_in = config.get_feed_in_settings(runtime_override=scenario_params)
    totals = _print_window_stats(anchor, cache)

    t0 = time.perf_counter()
    matrix, meta = build_historical_window_matrix(
        anchor, cache, prices, feed_in_settings=feed_in
    )
    t_matrix = time.perf_counter() - t0
    print(f"build_historical_window_matrix: {t_matrix:.3f} s")

    targets = meta["consumer_daily_targets_kwh"]
    print(f"Targets: {targets}")

    eauto = next(c for c in config.get_flexible_consumers(optimizer_only=True) if c["id"] == "eauto")
    ctx = resolve_charging_context(
        eauto,
        matrix,
        targets,
        logged_simulation=True,
    )
    print(f"E-Auto charging_context: use_time_window={ctx.get('use_time_window')}")

    if args.milp_only:
        battery = _scenario_to_battery_params(scenario_params)
        remaining = {cid: float(targets.get(cid, 0.0)) for cid in targets}
        t1 = time.perf_counter()
        milp_optimizer(
            matrix,
            matrix[0]["hour"],
            args.initial_soc,
            battery_params=battery,
            verbose=True,
            consumer_remaining_kwh=remaining,
            flex_indices=list(range(len(matrix))),
            charging_contexts={eauto["id"]: ctx},
            terminal_soc_percent=args.initial_soc,
        )
        t_milp = time.perf_counter() - t1
        print(f"milp_optimizer (1. Stunde): {t_milp:.3f} s")
        return

    battery = _scenario_to_battery_params(scenario_params)
    t1 = time.perf_counter()
    rows = simulate_horizon(
        matrix,
        args.initial_soc,
        battery_params=battery,
        verbose=False,
        consumer_daily_targets_kwh=targets,
    )
    t_sim = time.perf_counter() - t1
    print(f"simulate_horizon (24h): {t_sim:.3f} s")
    print(f"End-SOC: {rows[-1]['Simulierter SoC (%)']:.1f} %")


if __name__ == "__main__":
    main()
