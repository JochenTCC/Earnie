"""Debug: Warum weicht sunset-Grundlast von fixed_24h ab? Matrix- und Slot-Abgleich."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from data.data_loader import load_market_prices
from data.planning_window import normalize_hour_slot
from scripts.run_backtesting import resolve_backtesting_window
from simulation.backtesting_horizon import (
    compute_sunrise_planning_at_anchor,
    step_slot_datetimes,
)
from simulation.engine import (
    HistoricalDataCache,
    build_historical_matrix_for_slots,
    build_historical_window_matrix,
    build_sunrise_window_matrix,
    window_slot_datetimes,
)
from simulation.baseload_validation import resolve_hourly_baseload_kw

WINDOW = "2025-01-10T07:00:00"


def _parse_anchor(value: str) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.to_pydatetime()


def _slot_key(dt) -> str:
    return normalize_hour_slot(dt).isoformat()


def _matrix_baseload_sum(matrix: list[dict]) -> float:
    return round(sum(float(r["expected_p_act"]) for r in matrix), 3)


def _compare_slots(label: str, slots_a: list, slots_b: list) -> None:
    keys_a = [_slot_key(s) for s in slots_a]
    keys_b = [_slot_key(s) for s in slots_b]
    print(f"\n--- {label} ---")
    print(f"  len A={len(keys_a)}, len B={len(keys_b)}, equal={keys_a == keys_b}")
    if keys_a != keys_b:
        for index, (ka, kb) in enumerate(zip(keys_a, keys_b)):
            if ka != kb:
                print(f"  first diff at {index}: A={ka} B={kb}")
                break
        only_a = set(keys_a) - set(keys_b)
        only_b = set(keys_b) - set(keys_a)
        if only_a:
            print(f"  only in A: {sorted(only_a)[:3]}...")
        if only_b:
            print(f"  only in B: {sorted(only_b)[:3]}...")


def _compare_matrix_baseload(label: str, matrix_a: list[dict], matrix_b: list[dict]) -> None:
    print(f"\n--- {label} ---")
    sum_a = _matrix_baseload_sum(matrix_a)
    sum_b = _matrix_baseload_sum(matrix_b)
    print(f"  sum expected_p_act: A={sum_a}, B={sum_b}, delta={round(sum_a - sum_b, 3)}")
    diffs = []
    for ra, rb in zip(matrix_a, matrix_b):
        ka = _slot_key(ra["slot_datetime"])
        kb = _slot_key(rb["slot_datetime"])
        da = float(ra["expected_p_act"])
        db = float(rb["expected_p_act"])
        if ka != kb or abs(da - db) > 1e-6:
            diffs.append((ka, kb, da, db))
    print(f"  row diffs: {len(diffs)}")
    for item in diffs[:5]:
        print(f"    slot {item[0]} vs {item[1]}: {item[2]} vs {item[3]}")


def main() -> None:
    anchor = _parse_anchor(WINDOW)
    sim_cfg = config.get_scenario_explorer_conf()
    start, end = resolve_backtesting_window(
        pd.Timestamp(2025, 1, 1),
        pd.Timestamp(2026, 1, 1),
        sim_cfg.get("price_range", "last_12_months"),
    )
    cache = HistoricalDataCache()
    cache.load()
    prices_df = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )
    scenario = config.get_backtesting_scenarios()["battery_10kwh_dynamic"]
    feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario)

    print(f"=== Debug Matrix Alignment: {WINDOW} ===")

    fixed_matrix, fixed_meta = build_historical_window_matrix(
        anchor, cache, prices_df, feed_in_settings=feed_in
    )
    sunset_matrix, sunset_meta, sunrise_idx, _matrix_full = build_sunrise_window_matrix(
        anchor, cache, prices_df, scenario, feed_in_settings=feed_in
    )

    planning_window, sunrise_index_raw = compute_sunrise_planning_at_anchor(
        anchor, scenario
    )
    tz_name = config.get_planning_timezone()
    step_slots = step_slot_datetimes(anchor, tz_name)
    window_slots = window_slot_datetimes(anchor)

    full_matrix, _ = build_historical_matrix_for_slots(
        [normalize_hour_slot(dt).replace(tzinfo=None) if hasattr(dt, "tzinfo") and dt.tzinfo else dt
         for dt in planning_window.slot_datetimes],
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in,
        charging_anchor=anchor,
    )
    truncated = full_matrix[:24]

    _compare_slots("window_slots vs step_slots", window_slots, step_slots)
    _compare_slots("fixed matrix slots vs step_slots", [r["slot_datetime"] for r in fixed_matrix], step_slots)
    _compare_slots("sunset matrix slots vs step_slots", [r["slot_datetime"] for r in sunset_matrix], step_slots)
    _compare_slots("truncated full slots vs step_slots", [r["slot_datetime"] for r in truncated], step_slots)
    _compare_slots("planning_window first 24 vs step_slots", list(planning_window.slot_datetimes)[:24], step_slots)

    _compare_matrix_baseload("fixed vs sunset (returned matrix)", fixed_matrix, sunset_matrix)
    _compare_matrix_baseload("fixed vs truncated full", fixed_matrix, truncated)
    _compare_matrix_baseload("step_slots meta matrix vs fixed", fixed_matrix, fixed_matrix)

    print("\n--- Meta baseload (Plausibilitaets-Referenz) ---")
    print(f"  fixed meta baseload_kwh: {fixed_meta['baseload_kwh']}")
    print(f"  sunset meta baseload_kwh: {sunset_meta['baseload_kwh']}")
    print(f"  fixed matrix sum expected_p_act: {_matrix_baseload_sum(fixed_matrix)}")
    print(f"  sunset matrix sum expected_p_act: {_matrix_baseload_sum(sunset_matrix)}")
    print(f"  sunrise_index (raw): {sunrise_index_raw}, effective in build: {sunrise_idx}")

    # Rohdaten: stored vs derived fuer step_slots
    baseload_stored, totals, total_load, hourly_flex = cache.get_window_consumption(step_slots)
    derived_kw, derived_sum = resolve_hourly_baseload_kw(total_load, hourly_flex)
    print("\n--- CSV / derive ---")
    print(f"  stored sum: {round(sum(baseload_stored), 3)}")
    print(f"  derived sum: {derived_sum}")
    print(f"  total sum: {round(sum(total_load), 3)}")

    full_len = len(full_matrix)
    full_sum = _matrix_baseload_sum(full_matrix)
    trunc_sum = _matrix_baseload_sum(truncated)
    fixed_sum = _matrix_baseload_sum(fixed_matrix)
    sunset_sum = _matrix_baseload_sum(sunset_matrix)
    print("\n=== ROOT CAUSE CHECK ===")
    print(f"  Volles Sunset-Fenster: {full_len} h, Grundlast-Summe matrix={full_sum}")
    print(f"  Meta 24h-Schritt (Plausi-Referenz): {sunset_meta['baseload_kwh']} kWh")
    print(f"  Trunc24 ohne Overlay: {trunc_sum} kWh  |  sunset nach Overlay: {sunset_sum} kWh")
    print(f"  fixed_24h: {fixed_sum} kWh")
    if abs(fixed_sum - sunset_sum) < 0.01:
        print("  -> Sunset-Output-Grundlast stimmt mit fixed_24h ueberein (Overlay aktiv).")
    elif abs(fixed_sum - sunset_meta["baseload_kwh"]) < 0.01 and abs(trunc_sum - fixed_sum) > 0.01:
        print(
            "  -> Ursache: resolve_hourly_baseload_kw laeuft ueber volles SA2-Fenster, "
            "Plausibilitaet vergleicht aber nur die ersten 24 h Output."
        )


if __name__ == "__main__":
    main()
