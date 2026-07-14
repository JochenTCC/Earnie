"""Diagnose: einzelnes Backtesting-Fenster gezielt ausführen und timen."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GREENFIELD_CONFIG = ROOT / "greenfield" / "config"
GREENFIELD_RUNTIME = ROOT / "greenfield" / "runtime"

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")
sys.path.insert(0, str(ROOT))


def _apply_greenfield_env() -> None:
    os.environ["EARNIE_CONFIG_PATH"] = str(GREENFIELD_CONFIG / "config.json")
    os.environ["EARNIE_RUNTIME_DIR"] = str(GREENFIELD_RUNTIME)
    for suffix, name in (
        ("COMPONENTS_PATH", "components.json"),
        ("HOUSE_PROFILES_PATH", "house_profiles.json"),
        ("TARIFFS_PATH", "tariffs.json"),
        ("BACKTESTING_SCENARIOS_PATH", "backtesting_scenarios.json"),
    ):
        path = GREENFIELD_CONFIG / name
        if path.is_file():
            os.environ[f"EARNIE_{suffix}"] = str(path)


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
        help="Ankerzeitpunkt ISO (z. B. 2025-01-02 07:00:00)",
    )
    parser.add_argument(
        "--start-month",
        type=int,
        default=1,
        help="Startmonat für Fensterliste (Standard: 1)",
    )
    parser.add_argument(
        "--end-month",
        type=int,
        default=1,
        help="Endmonat für Fensterliste (Standard: 1)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="live",
        help="Szenario-ID aus backtesting_scenarios.json (Standard: live)",
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
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="MILP-Warnungen (z. B. Best-Effort-Ziele) auf stderr",
    )
    parser.add_argument(
        "--greenfield",
        action="store_true",
        help="Greenfield-Pfade (greenfield/config, greenfield/runtime)",
    )
    parser.add_argument(
        "--flex-diag",
        action="store_true",
        help="Phase-0: remaining_kwh, effective_target, eligible slots je Stunde",
    )
    parser.add_argument(
        "--compare",
        type=str,
        help="Komma-getrennte Szenario-IDs für Vergleich (z. B. s2-kein-pv,live)",
    )
    parser.add_argument(
        "--write-json",
        type=str,
        help="Pfad für JSON-Ergebnis (optional)",
    )
    return parser.parse_args()


def _load_anchor_by_hour_offset(
    hour_offset: int,
    start_month: int,
    end_month: int,
    *,
    config,
    resolve_backtesting_window,
    HistoricalDataCache,
    list_simulation_anchors,
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


def _scenario_params(scenario_id: str, config) -> dict:
    scenarios = config.get_backtesting_scenarios()
    if scenario_id not in scenarios:
        raise SystemExit(f"Szenario '{scenario_id}' nicht gefunden: {sorted(scenarios)}")
    return dict(scenarios[scenario_id])


def _price_window_for_anchor(anchor: datetime, start_month: int, end_month: int) -> tuple[int, int]:
    month = anchor.month
    if start_month == end_month:
        return start_month, end_month
    return month, min(12, month + 1)


def _format_remaining(remaining: dict[str, float]) -> str:
    parts = [f"{cid}={value:.2f}" for cid, value in sorted(remaining.items()) if value > 1e-6]
    return ", ".join(parts) if parts else "-"


def _print_delivery_diag(hour: int, uhrzeit: str, diag: dict[str, dict]) -> None:
    print(f"\n  [{hour:02d}] {uhrzeit}")
    print(f"       remaining: {_format_remaining({cid: d['remaining_kwh'] for cid, d in diag.items()})}")
    for cid, entry in sorted(diag.items()):
        if entry.get("remaining_kwh", 0.0) <= 0 and not entry.get("planned"):
            continue
        if "effective_target_kwh" not in entry:
            print(f"       {cid}: planned={entry.get('planned')} (no delivery constraint)")
            continue
        slots = entry.get("eligible_slots") or []
        slot_preview = ", ".join(slots[:6])
        if len(slots) > 6:
            slot_preview += f", ... (+{len(slots) - 6})"
        print(
            f"       {cid}: rem={entry['remaining_kwh']:.2f} "
            f"eff={entry['effective_target_kwh']:.2f} "
            f"max_del={entry['max_deliverable_kwh']:.2f} "
            f"gap={entry['target_gap_kwh']:.2f} "
            f"min_on={entry['min_on_hours']}h "
            f"eligible={entry['eligible_count']} [{slot_preview}]"
        )


def _run_flex_diag_trace(
    matrix: list,
    targets: dict[str, float],
    flex_consumers: list,
    battery_params: dict,
    initial_soc: float,
    *,
    verbose: bool,
) -> tuple[list[dict], dict[str, float], list[dict]]:
    from optimizer.charging_context import apply_horizon_charging_limits, resolve_charging_contexts
    from optimizer.filter_context import adjust_targets_for_native_filter, resolve_filter_contexts
    from optimizer.generic_flex_run import continue_on_from_state, update_generic_flex_run_state
    from optimizer.milp_consumers import delivery_constraint_diagnostics
    from optimizer.simulation import (
        _cap_flex_delivery,
        _simulate_single_hour_optimizer,
        finalize_chart_row_energy,
    )
    from optimizer.targets import consumer_column_name, resolve_horizon_consumer_targets_kwh

    charging_contexts = resolve_charging_contexts(matrix, targets, consumers=flex_consumers)
    horizon_limits = resolve_horizon_consumer_targets_kwh(
        matrix, targets, flexible_consumers=flex_consumers
    )
    horizon_limits = apply_horizon_charging_limits(horizon_limits, charging_contexts)
    filters = resolve_filter_contexts(matrix, flex_consumers)
    horizon_limits = adjust_targets_for_native_filter(
        horizon_limits, flex_consumers, matrix, filters
    )
    delivered_horizon = {consumer["id"]: 0.0 for consumer in flex_consumers}
    generic_flex_run: dict[str, dict] = {}
    chart_rows: list[dict] = []
    hour_traces: list[dict] = []
    sim_soc = initial_soc

    for i, row in enumerate(matrix):
        remaining = {
            consumer["id"]: max(
                0.0,
                horizon_limits.get(consumer["id"], 0.0)
                - delivered_horizon.get(consumer["id"], 0.0),
            )
            for consumer in flex_consumers
        }
        remaining_slice = matrix[i:]
        diag = delivery_constraint_diagnostics(
            remaining_slice,
            remaining,
            list(range(len(remaining_slice))),
            charging_contexts,
            flex_consumers,
            filter_contexts=filters,
            verbose=verbose,
        )
        continue_on = continue_on_from_state(
            {"generic_flex_run": generic_flex_run},
            flex_consumers,
        )
        sim_soc, chart_row, mode, target_power = _simulate_single_hour_optimizer(
            remaining_slice,
            row,
            sim_soc,
            battery_params,
            k_push=None,
            verbose=verbose,
            consumer_remaining_kwh=remaining,
            spa_remaining_kwh=None,
            flex_indices=list(range(len(remaining_slice))),
            charging_contexts=charging_contexts,
            filter_contexts=filters,
            terminal_soc_percent=initial_soc,
            sunrise_soc_min_index=None,
            matrix_hour_index=i,
            flexible_consumers=flex_consumers,
            consumer_continue_on=continue_on,
        )
        _cap_flex_delivery(chart_row, flex_consumers, horizon_limits, delivered_horizon)
        for consumer in flex_consumers:
            power = float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
            update_generic_flex_run_state(generic_flex_run, consumer, power)
        old_soc = float(chart_row["Simulierter SoC (%)"])
        sim_soc = finalize_chart_row_energy(
            chart_row, mode, target_power, old_soc, battery_params
        )
        chart_rows.append(chart_row)
        flex_kw = {
            consumer["id"]: float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
            for consumer in flex_consumers
        }
        trace = {
            "hour": i,
            "uhrzeit": chart_row.get("Uhrzeit"),
            "soc_start": round(old_soc, 1),
            "soc_end": round(sim_soc, 1),
            "steuerbefehl": chart_row.get("Steuerbefehl"),
            "remaining_kwh": {cid: round(value, 3) for cid, value in remaining.items()},
            "delivery_diag": diag,
            "flex_kw": {cid: round(kw, 3) for cid, kw in flex_kw.items()},
        }
        hour_traces.append(trace)
        has_activity = any(kw > 0 for kw in flex_kw.values()) or any(
            entry.get("target_gap_kwh", 0.0) > 1e-6 for entry in diag.values()
        )
        if has_activity or i in {0, 23}:
            _print_delivery_diag(i, str(chart_row.get("Uhrzeit")), diag)
            active = ", ".join(f"{cid}={kw:.2f}kW" for cid, kw in flex_kw.items() if kw > 0)
            print(
                f"       MILP t0: {active or '-'} | "
                f"{chart_row.get('Steuerbefehl')} | SOC {old_soc:.1f}->{sim_soc:.1f}%"
            )

    from optimizer.simulation import delivered_flex_kwh_from_rows

    delivered = delivered_flex_kwh_from_rows(chart_rows, flexible_consumers=flex_consumers)
    return chart_rows, delivered, hour_traces


def _run_scenario(
    scenario_id: str,
    anchor: datetime,
    args: argparse.Namespace,
    cache,
    prices,
    *,
    config,
    build_historical_window_matrix,
    _flexible_consumers_from_scenario,
    _scenario_to_battery_params,
    resolve_consumption_source,
) -> dict:
    from optimizer.charging_context import resolve_charging_contexts
    from optimizer.milp import milp_optimizer
    from optimizer.simulation import (
        delivered_flex_kwh_from_rows,
        simulate_horizon,
        total_consumption_kwh_from_rows,
    )

    scenario_params = _scenario_params(scenario_id, config)
    flex_consumers = _flexible_consumers_from_scenario(scenario_params)
    sim_cfg = config.get_file_paths_battery_simulation()
    feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)

    print(f"\n{'=' * 72}")
    print(f"Scenario: {scenario_id}")
    print(f"{'=' * 72}")

    t0 = time.perf_counter()
    matrix, meta = build_historical_window_matrix(
        anchor,
        cache,
        prices,
        feed_in_settings=feed_in,
        scenario_params=scenario_params,
    )
    print(f"build_historical_window_matrix: {time.perf_counter() - t0:.3f} s")
    print(f"consumption_source: {resolve_consumption_source(scenario_params)}")
    print(f"PV sum (kWh): {sum(float(r.get('expected_p_pv', 0) or 0) for r in matrix):.2f}")

    targets = dict(meta["consumer_daily_targets_kwh"])
    print(f"Targets: {targets}")

    battery = _scenario_to_battery_params(scenario_params)
    result: dict = {
        "scenario_id": scenario_id,
        "anchor": pd.Timestamp(anchor).isoformat(),
        "targets": targets,
        "spec_flex_targets": dict(meta.get("spec_flex_targets_kwh") or {}),
    }

    if args.flex_diag:
        print("\n--- Flex delivery trace (hours with activity, 0, 23) ---")
        rows, delivered, hour_traces = _run_flex_diag_trace(
            matrix,
            targets,
            flex_consumers,
            battery,
            args.initial_soc,
            verbose=args.verbose,
        )
        result["hour_traces"] = hour_traces
    elif args.milp_only:
        charging_contexts = resolve_charging_contexts(matrix, targets, consumers=flex_consumers)
        remaining = {cid: float(targets.get(cid, 0.0)) for cid in targets}
        t1 = time.perf_counter()
        milp_optimizer(
            matrix,
            matrix[0]["hour"],
            args.initial_soc,
            battery_params=battery,
            verbose=args.verbose,
            consumer_remaining_kwh=remaining,
            flex_indices=list(range(len(matrix))),
            charging_contexts=charging_contexts,
            consumers=flex_consumers,
            terminal_soc_percent=args.initial_soc,
        )
        print(f"milp_optimizer (1. Stunde): {time.perf_counter() - t1:.3f} s")
        return result

    else:
        t1 = time.perf_counter()
        rows = simulate_horizon(
            matrix,
            args.initial_soc,
            battery_params=battery,
            verbose=args.verbose,
            consumer_daily_targets_kwh=targets,
            flexible_consumers=flex_consumers,
        )
        print(f"simulate_horizon (24h): {time.perf_counter() - t1:.3f} s")
        delivered = delivered_flex_kwh_from_rows(rows, flexible_consumers=flex_consumers)

    print(f"End-SOC: {rows[-1]['Simulierter SoC (%)']:.1f} %")
    print(f"Delivered flex: {delivered}")
    print(f"Total consumption: {total_consumption_kwh_from_rows(rows):.3f} kWh")
    result["delivered_flex"] = delivered
    result["end_soc"] = float(rows[-1]["Simulierter SoC (%)"])
    return result


def _print_compare_summary(results: list[dict]) -> None:
    if len(results) < 2:
        return
    print(f"\n{'=' * 72}")
    print("Comparison summary")
    print(f"{'=' * 72}")
    base = results[0]
    ref = results[1]
    base_del = base.get("delivered_flex") or {}
    ref_del = ref.get("delivered_flex") or {}
    targets = base.get("targets") or {}
    print(f"{'Consumer':<16} {'Target':>8} {base['scenario_id']:>14} {ref['scenario_id']:>14} {'Diff':>8}")
    for cid in sorted(targets):
        target = float(targets.get(cid, 0.0))
        b = float(base_del.get(cid, 0.0))
        r = float(ref_del.get(cid, 0.0))
        print(f"{cid:<16} {target:8.3f} {b:14.3f} {r:14.3f} {b - r:+8.3f}")
    b_total = sum(float(v) for v in base_del.values())
    r_total = sum(float(v) for v in ref_del.values())
    t_total = sum(float(v) for v in targets.values())
    print(f"{'TOTAL flex':<16} {t_total:8.3f} {b_total:14.3f} {r_total:14.3f} {b_total - r_total:+8.3f}")


def main() -> None:
    args = _parse_args()
    if args.greenfield:
        _apply_greenfield_env()

    from runtime_store.config_load import load_config_or_exit

    config = load_config_or_exit()
    from data.data_loader import load_market_prices
    from scripts.run_backtesting import resolve_backtesting_window
    from simulation.engine import (
        HistoricalDataCache,
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
        build_historical_window_matrix,
        list_simulation_anchors,
        window_slot_datetimes,
    )

    if args.verbose:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.anchor:
        anchor = pd.Timestamp(args.anchor).to_pydatetime()
    elif args.hour_offset is not None:
        anchor, win_idx, anchors = _load_anchor_by_hour_offset(
            args.hour_offset,
            args.start_month,
            args.end_month,
            config=config,
            resolve_backtesting_window=resolve_backtesting_window,
            HistoricalDataCache=HistoricalDataCache,
            list_simulation_anchors=list_simulation_anchors,
        )
        print(
            f"Fortschritt {args.hour_offset}/{len(anchors) * 24} h "
            f"-> Fenster-Index {win_idx} (1-basiert: {win_idx + 1})"
        )
    else:
        raise SystemExit("Bitte --hour-offset oder --anchor angeben.")

    sim_cfg = config.get_file_paths_battery_simulation()
    price_start_month, price_end_month = _price_window_for_anchor(
        anchor, args.start_month, args.end_month
    )
    start, end = resolve_backtesting_window(
        pd.Timestamp(2025, price_start_month, 1),
        pd.Timestamp(2025, price_end_month, 1),
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
    slots = window_slot_datetimes(anchor)
    print(f"Anker:     {anchor}")
    print(f"Fenster:   {slots[0]} -> {slots[-1]}")
    print(f"initial_soc: {args.initial_soc}%")

    scenario_ids = [args.scenario]
    if args.compare:
        scenario_ids = [part.strip() for part in args.compare.split(",") if part.strip()]

    results = []
    for scenario_id in scenario_ids:
        results.append(
            _run_scenario(
                scenario_id,
                anchor,
                args,
                cache,
                prices,
                config=config,
                build_historical_window_matrix=build_historical_window_matrix,
                _flexible_consumers_from_scenario=_flexible_consumers_from_scenario,
                _scenario_to_battery_params=_scenario_to_battery_params,
                resolve_consumption_source=__import__(
                    "house_config.planning_flex_bridge", fromlist=["resolve_consumption_source"]
                ).resolve_consumption_source,
            )
        )

    _print_compare_summary(results)

    if args.write_json:
        out_path = Path(args.write_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
