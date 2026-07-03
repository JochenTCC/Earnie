"""Analyse des Backtesting-Benchmark-Fensters (Backlog: 2025-09-28)."""
from __future__ import annotations

import os
import time
from datetime import datetime

import pandas as pd

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

import config
from data.data_loader import load_market_prices
from optimizer.charging_context import (
    consumer_charging_eligible_indices,
    resolve_charging_context,
    schedule_indices_for_consumer,
)
from optimizer.consumer_power import uses_power_setpoint
from optimizer.milp import milp_optimizer
from optimizer.cbc_solver import apply_cbc_solver_env, clear_cbc_solver_env
from scripts.run_backtesting import resolve_backtesting_window
from simulation.engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    build_historical_window_matrix,
    list_simulation_anchors,
    window_slot_datetimes,
)


def _load_window(hour_offset: int = 1392):
    sim_cfg = config.get_file_paths_battery_simulation()
    start, end = resolve_backtesting_window(
        pd.Timestamp(2025, 8, 1),
        pd.Timestamp(2025, 9, 1),
        sim_cfg.get("price_range", "last_12_months"),
        sim_cfg["path_consumption"],
        sim_cfg["path_production"],
    )
    cache = HistoricalDataCache()
    cache.load()
    anchors = list_simulation_anchors(start, end, cache)
    idx = hour_offset // 24
    anchor = anchors[idx]
    prices = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )
    matrix, meta = build_historical_window_matrix(anchor, cache, prices)
    return anchor, idx, anchors, cache, matrix, meta


def _eauto_context(matrix, meta):
    eauto = next(
        c for c in config.get_flexible_consumers(optimizer_only=True) if c["id"] == "eauto"
    )
    targets = meta["consumer_daily_targets_kwh"]
    ctx = resolve_charging_context(
        eauto, matrix, targets, logged_simulation=True
    )
    sched_idx = schedule_indices_for_consumer(
        matrix, len(matrix), list(range(len(matrix))), eauto, ctx
    )
    eligible = consumer_charging_eligible_indices(matrix, eauto, sched_idx, ctx)
    return eauto, ctx, targets, sched_idx, eligible


def _print_window_summary(anchor, idx, anchors, cache, matrix, meta) -> None:
    slots = window_slot_datetimes(anchor)
    _, totals, loads, _ = cache.get_window_consumption(slots)
    pv = cache.get_pv_for_slots(slots)
    eauto, ctx, targets, sched_idx, eligible = _eauto_context(matrix, meta)

    print(f"=== Fenster Index {idx} | Anker {anchor} ===")
    print(f"Wochentag: {anchor.strftime('%A')} (ready_by aus Config)")
    print(f"Historisch (kWh): { {k: round(v, 3) for k, v in totals.items()} }")
    print(f"Gesamtlast 24h: {sum(loads):.2f} kWh | PV: {sum(pv):.2f} kWh")
    print(f"Targets MILP: {targets}")
    print(f"E-Auto power_setpoint (variable Leistung): {uses_power_setpoint(eauto)}")
    print(f"E-Auto use_time_window: {ctx.get('use_time_window')}")
    for key in (
        "target_kwh",
        "remaining_kwh",
        "window_start",
        "window_end",
        "urgent",
        "plugged_in",
    ):
        if key in ctx:
            print(f"  ctx.{key}: {ctx[key]}")
    print(
        f"Schedule-Indizes: {len(sched_idx)} h | "
        f"Eligible-Indizes: {len(eligible)} h"
    )
    if sched_idx:
        first = matrix[sched_idx[0]]["slot_datetime"]
        last = matrix[sched_idx[-1]]["slot_datetime"]
        print(f"  Schedule-Slots: {first} .. {last}")

    print("\n--- Nachbarfenster (E-Auto kWh) ---")
    for di in range(max(0, idx - 3), min(len(anchors), idx + 4)):
        a = anchors[di]
        sl = window_slot_datetimes(a)
        _, t, _, _ = cache.get_window_consumption(sl)
        mark = " <--" if di == idx else ""
        print(
            f"  [{di:2d}] {a.date()}  eauto={t.get('eauto', 0):.2f}  "
            f"swimspa={t.get('swimspa', 0):.2f}  wp={t.get('waermepumpe', 0):.2f}{mark}"
        )


def _time_milp(matrix, meta, *, strict: bool, label: str) -> float:
    scenario = config.get_backtesting_scenarios()["runtime_settings"]
    battery = _scenario_to_battery_params(scenario)
    eauto, ctx, targets, _, _ = _eauto_context(matrix, meta)
    remaining = {cid: float(targets.get(cid, 0.0)) for cid in targets}
    clear_cbc_solver_env()
    if strict:
        apply_cbc_solver_env(strict=True)
    t0 = time.perf_counter()
    milp_optimizer(
        matrix,
        matrix[0]["hour"],
        50.0,
        battery_params=battery,
        verbose=False,
        consumer_remaining_kwh=remaining,
        flex_indices=list(range(len(matrix))),
        charging_contexts={eauto["id"]: ctx},
        terminal_soc_percent=50.0,
    )
    return time.perf_counter() - t0


def main() -> None:
    anchor, idx, anchors, cache, matrix, meta = _load_window()
    _print_window_summary(anchor, idx, anchors, cache, matrix, meta)

    print("\n--- MILP Laufzeit Stunde 0 (ein Aufruf) ---")
    t_rel = _time_milp(matrix, meta, strict=False, label="gapRel 10%")
    print(f"  gapRel 10% (Default): {t_rel:.2f} s")
    import sys
    if "--with-strict" in sys.argv:
        t_strict = _time_milp(matrix, meta, strict=True, label="cbc strict")
        print(f"  CBC strict:           {t_strict:.2f} s")
        if t_strict > 0:
            print(f"  Faktor strict/default: {t_strict / max(t_rel, 0.001):.1f}x")
    else:
        print("  (CBC strict übersprungen; --with-strict für Vergleich)")

    # Degenerations-Check: viele gleichwertige Lösungen?
    eauto_kwh = meta["consumer_daily_targets_kwh"].get("eauto", 0.0)
    pv_kwh = sum(row["expected_p_pv"] for row in matrix)
    print("\n--- Einordnung ---")
    print(f"E-Auto-Ziel im MILP: {eauto_kwh:.3f} kWh (historisch geloggt)")
    if eauto_kwh < 0.5:
        print(
            "Wenig E-Auto-Last: Optimierungsspielraum gering, "
            "aber MILP-Struktur (Zeitfenster + variable Leistung) bleibt voll aktiv."
        )


if __name__ == "__main__":
    main()
