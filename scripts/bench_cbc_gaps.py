"""Sensibilitätstests für CBC-Gap- und Toleranz-Einstellungen (ein Backtesting-Fenster)."""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from data.data_loader import load_market_prices
from optimizer.cbc_solver import (
    apply_cbc_solver_env,
    clear_cbc_solver_env,
    cbc_solver_settings_resolved,
)
from optimizer.simulation import calculate_step_cost_euro_from_row
from optimizer.simulation import simulate_horizon
from optimizer.targets import consumer_column_name
from scripts.run_backtesting import resolve_backtesting_window
from simulation.engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    build_historical_window_matrix,
    list_simulation_anchors,
    validate_window_consumption,
    window_slot_datetimes,
)


@dataclass(frozen=True)
class GapCase:
    case_id: str
    gap_rel: float | None = None
    gap_abs: float | None = None
    primal_tolerance: float | None = None
    integer_tolerance: float | None = None
    strict: bool = False


# Reihenfolge: größte Toleranz zuerst (gapRel in 5%-Schritten, min. 10 %), cbc_strict zuletzt.
DEFAULT_CASES: tuple[GapCase, ...] = (
    GapCase("gapRel_0.20", gap_rel=0.20),
    GapCase("gapRel_0.15", gap_rel=0.15),
    GapCase("gapRel_0.10", gap_rel=0.10),
    GapCase("gapAbs_50", gap_abs=50.0),
    GapCase("gapRel_0.10_abs_50", gap_rel=0.10, gap_abs=50.0),
    GapCase("cbc_strict", strict=True),
)


@dataclass
class GapCaseResult:
    case_id: str
    settings: dict
    seconds: float
    cost_euro: float
    end_soc: float
    eauto_delivered_kwh: float
    eauto_target_kwh: float
    automatik_hours: int
    plausibility_ok: bool
    plausibility_diff_kwh: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CBC-Gap-Sensibilität auf einem historischen 24h-Fenster.",
    )
    parser.add_argument("--hour-offset", type=int, default=1392)
    parser.add_argument("--start-month", type=int, default=8)
    parser.add_argument("--end-month", type=int, default=9)
    parser.add_argument("--scenario", type=str, default="runtime_settings")
    parser.add_argument("--initial-soc", type=float, default=50.0)
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="CBC-Strict-Fall (cbc_strict, ohne gapRel) überspringen.",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        metavar="CASE_ID",
        help=f"Teilmenge der Fälle ({', '.join(c.case_id for c in DEFAULT_CASES)}).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="CBC-Fälle parallel in N Prozessen (Default: 1 = Reihenfolge der Fälle; >1 parallel).",
    )
    return parser.parse_args()


def _resolve_anchor(hour_offset: int, start_month: int, end_month: int) -> datetime:
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
            f"hour-offset {hour_offset} ausserhalb (0..{len(anchors) * 24 - 1})."
        )
    return anchors[win_idx]


def _selected_cases(args: argparse.Namespace) -> list[GapCase]:
    cases = list(DEFAULT_CASES)
    if args.skip_baseline:
        cases = [c for c in cases if c.case_id != "cbc_strict"]
    if args.cases:
        wanted = set(args.cases)
        cases = [c for c in cases if c.case_id in wanted]
        missing = wanted - {c.case_id for c in cases}
        if missing:
            raise SystemExit(f"Unbekannte case_id(s): {sorted(missing)}")
    return cases


def _print_case_done(result: GapCaseResult) -> None:
    print(
        f"Fertig [{result.case_id}] in {result.seconds:.1f} s, "
        f"Kosten {result.cost_euro:.4f} EUR, "
        f"E-Auto {result.eauto_delivered_kwh:.3f} kWh"
    )


def _run_cases_serial(
    cases: list[GapCase],
    anchor: datetime,
    matrix_template: list[dict],
    meta: dict,
    scenario_params: dict,
    initial_soc: float,
) -> list[GapCaseResult]:
    results: list[GapCaseResult] = []
    for case in cases:
        print(f"\n--- {case.case_id} ---")
        result = _run_case(
            case,
            anchor,
            matrix_template,
            meta,
            scenario_params,
            initial_soc,
        )
        results.append(result)
        _print_case_done(result)
    return results


def _run_cases_parallel(
    cases: list[GapCase],
    anchor: datetime,
    matrix_template: list[dict],
    meta: dict,
    scenario_params: dict,
    initial_soc: float,
    workers: int,
) -> list[GapCaseResult]:
    results_by_id: dict[str, GapCaseResult] = {}
    print(f"\nStarte {len(cases)} Fälle mit {workers} Worker(n)...")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_case,
                case,
                anchor,
                matrix_template,
                meta,
                scenario_params,
                initial_soc,
            ): case.case_id
            for case in cases
        }
        for future in as_completed(futures):
            result = future.result()
            results_by_id[result.case_id] = result
            _print_case_done(result)
    return [results_by_id[case.case_id] for case in cases]


def _run_case(
    case: GapCase,
    anchor: datetime,
    matrix_template: list[dict],
    meta: dict,
    scenario_params: dict,
    initial_soc: float,
) -> GapCaseResult:
    if case.strict:
        apply_cbc_solver_env(strict=True)
    else:
        apply_cbc_solver_env(
            gap_rel=case.gap_rel,
            gap_abs=case.gap_abs,
            primal_tolerance=case.primal_tolerance,
            integer_tolerance=case.integer_tolerance,
        )
    settings = cbc_solver_settings_resolved()
    matrix = [dict(row) for row in matrix_template]
    battery = _scenario_to_battery_params(scenario_params)
    t0 = time.perf_counter()
    rows = simulate_horizon(
        matrix,
        initial_soc,
        battery_params=battery,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
    )
    seconds = time.perf_counter() - t0
    plausibility = validate_window_consumption(rows, meta)
    eauto = next(c for c in config.get_flexible_consumers(optimizer_only=True) if c["id"] == "eauto")
    eauto_col = consumer_column_name(eauto)
    eauto_target = float(meta["consumer_daily_targets_kwh"].get("eauto", 0.0))
    eauto_delivered = sum(float(row.get(eauto_col, 0.0) or 0.0) for row in rows)
    automatik_hours = sum(
        1 for row in rows if str(row.get("Steuerbefehl", "")).strip() == "Automatik"
    )
    cost_euro = sum(calculate_step_cost_euro_from_row(row) for row in rows)
    return GapCaseResult(
        case_id=case.case_id,
        settings=settings,
        seconds=seconds,
        cost_euro=cost_euro,
        end_soc=float(rows[-1]["Simulierter SoC (%)"]),
        eauto_delivered_kwh=round(eauto_delivered, 3),
        eauto_target_kwh=round(eauto_target, 3),
        automatik_hours=automatik_hours,
        plausibility_ok=plausibility.ok,
        plausibility_diff_kwh=float(plausibility.diff_kwh),
    )


def _print_results(results: list[GapCaseResult]) -> None:
    reference_cost = next(
        (r.cost_euro for r in results if r.case_id == "gapRel_0.10"),
        None,
    )
    if reference_cost is None:
        reference_cost = next(
            (r.cost_euro for r in results if r.case_id == "cbc_strict"),
            None,
        )
    print("\n=== CBC-Gap-Sensibilität ===")
    header = (
        f"{'Fall':<22} {'s':>8} {'EUR':>9} {'ΔEUR':>8} {'Δ%':>7} "
        f"{'EAuto kWh':>10} {'Auto h':>7} {'Plaus.':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in results:
        if reference_cost is not None and row.case_id not in ("gapRel_0.10", "cbc_strict"):
            delta_eur = row.cost_euro - reference_cost
            delta_pct = (delta_eur / reference_cost * 100.0) if reference_cost else 0.0
            delta_eur_s = f"{delta_eur:+.4f}"
            delta_pct_s = f"{delta_pct:+.3f}"
        else:
            delta_eur_s = "—"
            delta_pct_s = "—"
        plaus = "OK" if row.plausibility_ok else "WARN"
        print(
            f"{row.case_id:<22} {row.seconds:8.1f} {row.cost_euro:9.4f} "
            f"{delta_eur_s:>8} {delta_pct_s:>7} "
            f"{row.eauto_delivered_kwh:6.3f}/{row.eauto_target_kwh:<3.3f} "
            f"{row.automatik_hours:7d} {plaus:>7}"
        )
        if row.settings:
            print(f"  settings: {row.settings}")
    print("============================\n")


def main() -> None:
    args = _parse_args()
    if args.workers < 1:
        raise SystemExit("--workers muss >= 1 sein.")
    cases = _selected_cases(args)
    if not cases:
        raise SystemExit(
            "Keine CBC-Fälle ausgewählt (prüfe --skip-baseline und --cases)."
        )
    scenario_params = dict(config.get_backtesting_scenarios()[args.scenario])
    anchor = _resolve_anchor(args.hour_offset, args.start_month, args.end_month)

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
    feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
    slots = window_slot_datetimes(anchor)
    _, totals, _, _ = cache.get_window_consumption(slots)

    print(f"Anker: {anchor}  (hour-offset {args.hour_offset})")
    print(f"Szenario: {args.scenario}")
    print(f"Fälle: {len(cases)}  |  Worker: {args.workers}")
    print(f"E-Auto historisch: {totals.get('eauto', 0.0):.3f} kWh")

    matrix, meta = build_historical_window_matrix(
        anchor, cache, prices, feed_in_settings=feed_in
    )
    matrix_template = [dict(row) for row in matrix]

    run_kwargs = {
        "cases": cases,
        "anchor": anchor,
        "matrix_template": matrix_template,
        "meta": meta,
        "scenario_params": scenario_params,
        "initial_soc": args.initial_soc,
    }
    try:
        if args.workers == 1:
            results = _run_cases_serial(**run_kwargs)
        else:
            results = _run_cases_parallel(**run_kwargs, workers=args.workers)
    finally:
        clear_cbc_solver_env()

    _print_results(results)


if __name__ == "__main__":
    main()
