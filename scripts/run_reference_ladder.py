# scripts/run_reference_ladder.py
"""Study export: one SE run, then L0–L3 per day and scenario and the rule sensitivity as CSV.

    python -m scripts.run_reference_ladder --scenario live --workers 8 --output-dir out

Spec: ``docs/dev/rule-based-reference.md`` §§ 4.7, 5. L3 plans with perfect foresight, so
L2 − L3 is an upper bound; final study figures also need the SE forecast mode.
"""
import os

if __name__ == "__main__":
    # Same as run_backtesting: only in the batch process, not on import.
    os.environ["EARNIE_OFFLINE"] = "1"

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from scripts.run_backtesting import (
    PRICE_STRATEGY_PERFECT,
    _parse_month,
    _price_load_window,
    config,
    load_run_prices,
    main as run_backtesting_main,
    scenarios_for_period,
)
from simulation.backtesting_log import load_backtesting_log
from simulation.engine import HistoricalDataCache
from simulation.period_clip import clip_results_to_period
from simulation.reference_costs import LADDER_L2
from simulation.reference_ladder import (
    SE_START_SOC_PERCENT,
    compute_l2_reference_costs,
    period_end_exclusive,
    soc_at_period_end,
)
from simulation.reference_ladder_export import (
    DAILY_CSV,
    SENSITIVITY_CSV,
    SUMMARY_CSV,
    SensitivityRun,
    daily_ladder_frame,
    rule_key,
    sensitivity_frame,
    sensitivity_grid,
    summary_frame,
    write_csv,
)


def _run_sensitivity_worker(
    ref_id: str,
    rule_params: dict,
    start_iso: str,
    end_iso: str,
    prices: pd.DataFrame,
    scenario_params: dict,
    horizon_mode: str,
) -> tuple[str, dict, SensitivityRun]:
    """Top-level worker for one L2 run with other rule parameters (Windows spawn)."""
    from data.cons_data_season_mirror import is_season_mirror_enabled

    start, end = pd.Timestamp(start_iso), pd.Timestamp(end_iso)
    cache = HistoricalDataCache(
        season_mirror_window=(start, end) if is_season_mirror_enabled() else None
    )
    cache.load()
    result = compute_l2_reference_costs(
        start,
        end,
        scenario_params,
        prices,
        cache,
        initial_soc=SE_START_SOC_PERCENT,
        horizon_mode=horizon_mode,
        rule_params=rule_params,
    )
    return (
        ref_id,
        rule_params,
        SensitivityRun(
            float(clip_results_to_period(result.frame, start, end)["sim_cost"].sum()),
            soc_at_period_end(result.frame, period_end_exclusive(end)),
            len(result.plausibility.failed),
        ),
    )


def _run_sensitivity(
    meta: dict,
    scenarios: dict[str, dict],
    prices: pd.DataFrame,
    grid: list[dict],
    workers: int,
) -> dict[tuple[str, tuple[float, str]], SensitivityRun]:
    """The grid without the default (the SE run has it), per setup: shared runs stay shared."""
    period = meta["period"]
    start, end = pd.Timestamp(period["start"]), pd.Timestamp(period["end"])
    owners: dict[str, dict] = {}
    for scenario_id, steps in meta["ladder_by_scenario"].items():
        owners.setdefault(steps[LADDER_L2], scenarios[scenario_id])
    variants = grid[1:]
    print(f"\nSensitivität: {len(owners)} Setup(s) × {len(variants)} Regel-Varianten...")
    runs: dict[tuple[str, tuple[float, str]], SensitivityRun] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_sensitivity_worker,
                ref_id,
                rule_params,
                start.isoformat(),
                end.isoformat(),
                prices,
                dict(params),
                period["horizon_mode"],
            ): (ref_id, rule_params)
            for ref_id, params in owners.items()
            for rule_params in variants
        }
        for future in as_completed(futures):
            ref_id, rule_params = futures[future]
            try:
                _, _, run = future.result()
            except Exception as exc:
                raise RuntimeError(
                    f"Sensitivität {ref_id} mit {rule_params} fehlgeschlagen: {exc}"
                ) from exc
            runs[(ref_id, rule_key(rule_params))] = run
            print(f"  Fertig: {ref_id} {rule_key(rule_params)}")
    return runs


def _print_summary(summary: pd.DataFrame, sensitivity: pd.DataFrame | None) -> None:
    print("\n=== REFERENZLEITER ===")
    print("L3 plant mit perfekter Voraussicht, L2 − L3 ist eine Obergrenze. Strom ohne Fixkosten und Brennstoff.")
    for row in summary.itertuples():
        share = f"{row.rule_share:.0%}" if pd.notna(row.rule_share) else "—"
        rod = " · Heizstab: L2 − L3 zu hoch" if row.heating_rod else ""
        print(
            f"  {row.scenario_label}: L0 {row.l0_eur:,.2f} € · L1 {row.l1_eur:,.2f} € · "
            f"L2 {row.l2_eur:,.2f} € · L3 {row.l3_eur:,.2f} € · "
            f"L2 − L3 {row.saving_l2_l3_eur:+,.2f} € · Regel-Anteil {share}{rod}"
        )
        if sensitivity is None:
            continue
        part = sensitivity.loc[sensitivity["scenario_id"] == row.scenario_id]
        best = part.loc[part["is_best_in_hindsight"]].iloc[0]
        print(
            f"    Bestes Regel-Set im Nachhinein: Quantil {best.lock_quantile:.2f}, "
            f"{best.surplus_priority}, L2 − L3 {best.saving_l2_l3_eur:+,.2f} €"
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Referenzleiter L0–L3 je Tag und Szenario als CSV, mit Regel-Sensitivität.",
    )
    parser.add_argument("--scenario", action="append", metavar="ID", help="Szenario (mehrfach möglich; Standard: alle).")
    parser.add_argument("--workers", type=int, required=True, metavar="N", help="Parallele Worker.")
    parser.add_argument("--output-dir", required=True, metavar="PFAD", help="Zielordner für SE-Log und CSVs.")
    parser.add_argument("--start-month", metavar="MONAT", help="Erster Monat (1–12).")
    parser.add_argument("--end-month", metavar="MONAT", help="Letzter Monat (1–12).")
    parser.add_argument(
        "--skip-sensitivity",
        action="store_true",
        help="Nur den Export, ohne die 7 zusätzlichen L2-Läufe je Setup.",
    )
    parser.add_argument("--allow-stale-cons-data", action="store_true", help="Wie bei run_backtesting.")
    return parser


def _backtesting_argv(args: argparse.Namespace) -> list[str]:
    argv = ["--workers", str(args.workers), "--output-dir", args.output_dir]
    for scenario_id in args.scenario or []:
        argv += ["--scenario", scenario_id]
    if args.start_month:
        argv += ["--start-month", args.start_month]
    if args.end_month:
        argv += ["--end-month", args.end_month]
    if args.allow_stale_cons_data:
        argv.append("--allow-stale-cons-data")
    return argv


def main(argv: list[str] | None = None) -> None:
    args = _build_arg_parser().parse_args(argv)
    if args.start_month:
        _parse_month(args.start_month)
    if args.end_month:
        _parse_month(args.end_month)
    os.makedirs(args.output_dir, exist_ok=True)
    run_backtesting_main(_backtesting_argv(args))

    meta, hourly = load_backtesting_log(args.output_dir)
    period = meta["period"]
    start, end = pd.Timestamp(period["start"]), pd.Timestamp(period["end"])
    all_scenarios = scenarios_for_period(
        config.get_backtesting_scenarios(), start, end, period["horizon_mode"]
    )
    scenarios = {sid: all_scenarios[sid] for sid in meta["ladder_by_scenario"]}

    write_csv(daily_ladder_frame(meta, hourly, scenarios), os.path.join(args.output_dir, DAILY_CSV))
    summary = summary_frame(meta, hourly, scenarios)
    sensitivity = None
    if not args.skip_sensitivity:
        grid = sensitivity_grid()
        load_start, load_end = _price_load_window(start, end, PRICE_STRATEGY_PERFECT)
        live_params = all_scenarios.get(meta["live_scenario_id"]) or next(iter(all_scenarios.values()))
        prices = load_run_prices(
            load_start, load_end, config.get_scenario_explorer_conf(), live_params
        )
        runs = _run_sensitivity(meta, scenarios, prices, grid, args.workers)
        sensitivity = sensitivity_frame(meta, hourly, scenarios, runs, grid)
        write_csv(sensitivity, os.path.join(args.output_dir, SENSITIVITY_CSV))
    write_csv(summary, os.path.join(args.output_dir, SUMMARY_CSV))
    _print_summary(summary, sensitivity)
    print(f"\nExport: {os.path.abspath(args.output_dir)}")


if __name__ == "__main__":
    main()
