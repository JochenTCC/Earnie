"""Plausibilitäts-Warnungen aus backtesting_log.json pro Fenster aufschlüsseln."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from data.data_loader import load_market_prices
from optimizer.simulation import delivered_flex_kwh_from_rows, total_consumption_kwh_from_rows
from scripts.run_backtesting import resolve_backtesting_window
from simulation.backtesting_log import BACKTESTING_LOG_JSON, load_backtesting_log
from simulation.engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    build_historical_window_matrix,
    list_simulation_anchors,
    simulate_horizon,
    window_slot_datetimes,
)


def _parse_window_end(value: str) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.to_pydatetime()


def _load_failures(
    log_path: Path,
    scenario_id: str,
) -> list[dict]:
    if log_path.is_file():
        meta, _ = load_backtesting_log(str(log_path.parent))
        block = meta.get("plausibility", {}).get(scenario_id, {})
        return list(block.get("failures", []))
    raise FileNotFoundError(
        f"Keine Backtesting-Logdatei unter {log_path}. "
        "Zuerst Backtesting ausführen."
    )


def _find_anchor(anchors: list[datetime], window_end: datetime) -> datetime | None:
    for anchor in anchors:
        if anchor == window_end:
            return anchor
    return None


def _flex_delta_table(
    historical_totals: dict[str, float],
    delivered: dict[str, float],
) -> list[tuple[str, float, float, float]]:
    rows: list[tuple[str, float, float, float]] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        hist = float(historical_totals.get(cid, 0.0))
        opt = float(delivered.get(cid, 0.0))
        rows.append((cid, hist, opt, round(opt - hist, 3)))
    return rows


def _simulate_failure_window(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
) -> tuple[list[dict], dict]:
    matrix, meta = build_historical_window_matrix(anchor, cache, prices_df)
    battery_params = _scenario_to_battery_params(scenario_params)
    chart_rows = simulate_horizon(
        matrix,
        initial_soc=50.0,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
    )
    return chart_rows, meta


def analyze_failure(
    failure: dict,
    *,
    cache: HistoricalDataCache,
    anchors: list[datetime],
    prices_df: pd.DataFrame,
    scenario_params: dict,
) -> dict:
    window_end = _parse_window_end(failure["window_end"])
    anchor = _find_anchor(anchors, window_end)
    if anchor is None:
        return {
            "window_end": failure["window_end"],
            "error": "Anker nicht in Simulationsfenstern gefunden",
        }

    chart_rows, meta = _simulate_failure_window(
        anchor, cache, prices_df, scenario_params
    )
    flex_consumers = meta.get("_flexible_consumers")
    delivered = delivered_flex_kwh_from_rows(
        chart_rows,
        flexible_consumers=flex_consumers,
    )
    optimized_kwh = total_consumption_kwh_from_rows(chart_rows)
    baseload_kwh = round(
        sum(float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0) for row in chart_rows),
        3,
    )
    hist_baseload = float(meta.get("baseload_kwh", 0.0))
    baseload_adj = float(meta.get("baseload_adjustment_kwh", 0.0))
    flex_table = _flex_delta_table(meta["historical_totals"], delivered)
    return {
        "window_end": failure["window_end"],
        "historical_total_kwh": failure["historical_kwh"],
        "optimized_total_kwh": optimized_kwh,
        "log_diff_kwh": failure["diff_kwh"],
        "baseload_kwh": baseload_kwh,
        "historical_baseload_kwh": hist_baseload,
        "baseload_delta_kwh": round(baseload_kwh - hist_baseload, 3),
        "baseload_adjustment_kwh": baseload_adj,
        "flex_by_consumer": [
            {
                "consumer_id": cid,
                "historical_kwh": hist,
                "delivered_kwh": opt,
                "delta_kwh": delta,
            }
            for cid, hist, opt, delta in flex_table
        ],
        "targets_kwh": dict(meta["consumer_daily_targets_kwh"]),
    }


def _print_report(results: list[dict]) -> None:
    print(f"\n=== Plausibilitäts-Analyse ({len(results)} Fenster) ===\n")
    for item in results:
        if "error" in item:
            print(f"{item['window_end']}: FEHLER – {item['error']}")
            continue
        print(f"--- Fenster Ende {item['window_end']} ---")
        print(
            f"  Gesamt: hist={item['historical_total_kwh']:.2f} kWh, "
            f"opt={item['optimized_total_kwh']:.2f} kWh, "
            f"Δ={item['optimized_total_kwh'] - item['historical_total_kwh']:+.2f} kWh"
        )
        print(f"  Grundlast: {item['baseload_kwh']:.2f} kWh (hist {item['historical_baseload_kwh']:.2f}, Δ {item['baseload_delta_kwh']:+.2f})")
        if abs(item.get("baseload_adjustment_kwh", 0.0)) > 0.01:
            print(
                f"  CSV-Grundlast-Korrektur (stored−derived): "
                f"{item['baseload_adjustment_kwh']:+.2f} kWh"
            )
        print("  Flex je Verbraucher (hist → opt, Δ):")
        for row in item["flex_by_consumer"]:
            if abs(row["delta_kwh"]) < 0.01 and row["historical_kwh"] < 0.01:
                continue
            print(
                f"    {row['consumer_id']:12s}: "
                f"{row['historical_kwh']:6.2f} → {row['delivered_kwh']:6.2f}  "
                f"Δ={row['delta_kwh']:+.2f} kWh"
            )
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plausibilitäts-Warnungen aus backtesting_log.json aufschlüsseln."
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(BACKTESTING_LOG_JSON),
        help="Pfad zu backtesting_log.json",
    )
    parser.add_argument(
        "--scenario",
        default="battery_10kwh_dynamic",
        help="Szenario-ID in meta.plausibility",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max. Anzahl Fenster (0 = alle)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional: Ergebnis als JSON speichern",
    )
    args = parser.parse_args()

    failures = _load_failures(args.log, args.scenario)
    if args.limit > 0:
        failures = failures[: args.limit]

    sim_cfg = config.get_file_paths_battery_simulation()
    if args.log.is_file():
        meta_log, _ = load_backtesting_log(str(args.log.parent))
        period = meta_log.get("period", {})
        start_default = pd.Timestamp(period.get("start", "2025-01-01"))
        end_default = pd.Timestamp(period.get("end", "2026-01-01"))
    else:
        start_default = pd.Timestamp(2025, 1, 1)
        end_default = pd.Timestamp(2026, 1, 1)
    start, end = resolve_backtesting_window(
        start_default,
        end_default,
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
    live_id = config.get_live_scenario_id()
    scenario_params = config.get_backtesting_scenarios()[live_id]

    results = [
        analyze_failure(
            failure,
            cache=cache,
            anchors=anchors,
            prices_df=prices_df,
            scenario_params=scenario_params,
        )
        for failure in failures
    ]
    _print_report(results)

    if args.json_out is not None:
        args.json_out.write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"JSON gespeichert: {args.json_out}")


if __name__ == "__main__":
    main()
