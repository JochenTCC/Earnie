# scripts/run_reference_ladder.py
"""Study export: one SE run, then L0–L3 per day and scenario and the rule sensitivity as CSV.

    python -m scripts.run_reference_ladder --scenario live --workers 8 --output-dir out \
        --forecast-price-strategy mirror

Spec: ``docs/dev/rule-based-reference.md`` §§ 4.7, 5; ``docs/dev/se-forecast-mode.md`` § 4. A
second SE run in forecast mode goes to ``<output-dir>/forecast_mode``. Perfect foresight is the
upper bound of L2 − L3, the forecast run the lower one; ``--skip-forecast`` leaves it out.
Electricity, fuel and both are separate columns; ``*_with_fuel_*`` is the saving including fuel.
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
from simulation.forecast_mode import PLAN_ALL, PLAN_PRICE, parse_plan_forecast
from simulation.heat_fuel import heat_fuel_for_result
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
    ForecastRun,
    SensitivityRun,
    assert_references_match,
    daily_ladder_frame,
    rule_key,
    sensitivity_frame,
    sensitivity_grid,
    summary_frame,
    write_csv,
)

FORECAST_SUBDIR = "forecast_mode"


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
    clipped = clip_results_to_period(result.frame, start, end)
    return (
        ref_id,
        rule_params,
        SensitivityRun(
            float(clipped["sim_cost"].sum()),
            soc_at_period_end(result.frame, period_end_exclusive(end)),
            len(result.plausibility.failed),
            float(heat_fuel_for_result(clipped, scenario_params)["fuel_eur"]),
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
    print("L3 plant mit perfekter Voraussicht, L2 − L3 ist eine Obergrenze. L0 bis L3 sind Strom ohne Fixkosten.")
    has_forecast = "l3_forecast_eur" in summary.columns
    for row in summary.itertuples():
        share = f"{row.rule_share:.0%}" if pd.notna(row.rule_share) else "—"
        # A rod beside an electric source stays at 0 kWh in L2 (spec § 3.1).
        rod = " · Heizstab: L2 − L3 zu hoch" if row.heating_rod and not row.fuel_carriers else ""
        print(
            f"  {row.scenario_label}: L0 {row.l0_eur:,.2f} € · L1 {row.l1_eur:,.2f} € · "
            f"L2 {row.l2_eur:,.2f} € · L3 {row.l3_eur:,.2f} € · "
            f"L2 − L3 {row.saving_l2_l3_eur:+,.2f} € · Regel-Anteil {share}{rod}"
        )
        if row.fuel_carriers:
            share_all_in = f"{row.rule_share_with_fuel:.0%}" if pd.notna(row.rule_share_with_fuel) else "—"
            print(
                f"    Mit Brennstoff ({row.fuel_carriers}): L0 {row.l0_total_eur:,.2f} € · "
                f"L1 {row.l1_total_eur:,.2f} € · L2 {row.l2_total_eur:,.2f} € · L3 {row.l3_total_eur:,.2f} € · "
                f"L2 − L3 {row.saving_l2_l3_with_fuel_eur:+,.2f} € · Regel-Anteil {share_all_in}"
            )
        if has_forecast:
            print(
                f"    Forecast-Modus ({row.plan_forecast}, Preise {row.price_strategy}): "
                f"L3 {row.l3_forecast_eur:,.2f} € · L2 − L3 {row.saving_l2_l3_forecast_eur:+,.2f} € · "
                f"mit Brennstoff {row.saving_l2_l3_with_fuel_forecast_eur:+,.2f} €"
            )
        if sensitivity is None:
            continue
        part = sensitivity.loc[sensitivity["scenario_id"] == row.scenario_id]
        best = part.loc[part["is_best_in_hindsight"]].iloc[0]
        print(
            f"    Bestes Regel-Set im Nachhinein: Quantil {best.lock_quantile:.2f}, "
            f"{best.surplus_priority}, L2 − L3 {best.saving_l2_l3_eur:+,.2f} €, "
            f"mit Brennstoff {best.saving_l2_l3_with_fuel_eur:+,.2f} €"
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
    parser.add_argument(
        "--skip-forecast",
        action="store_true",
        help="Ohne zweiten SE-Lauf im Forecast-Modus: nur die Obergrenze von L2 − L3.",
    )
    parser.add_argument(
        "--plan-forecast",
        default=",".join(PLAN_ALL),
        metavar="EINGABEN",
        help=f"Prognosen des zweiten Laufs (Standard: {','.join(PLAN_ALL)}).",
    )
    parser.add_argument(
        "--forecast-price-strategy",
        choices=("mirror", "forecast"),
        help="Preise, die der Plan des zweiten Laufs noch nicht kennt. Pflicht, solange er Preisprognosen plant.",
    )
    parser.add_argument("--feature-dataset", metavar="CSV", help="Wie bei run_backtesting.")
    parser.add_argument("--forecast-model", metavar="JSON", help="Wie bei run_backtesting.")
    return parser


def _forecast_argv(args: argparse.Namespace, forecast_dir: str) -> list[str]:
    argv = [*_backtesting_argv(args, forecast_dir), f"--plan-forecast={args.plan_forecast}"]
    if args.forecast_price_strategy:
        argv += ["--price-strategy", args.forecast_price_strategy]
    if args.feature_dataset:
        argv += ["--feature-dataset", args.feature_dataset]
    if args.forecast_model:
        argv += ["--forecast-model", args.forecast_model]
    return argv


def _validate_forecast_args(args: argparse.Namespace) -> None:
    if args.skip_forecast:
        return
    plans_prices = PLAN_PRICE in parse_plan_forecast(args.plan_forecast)
    if plans_prices != bool(args.forecast_price_strategy):
        raise SystemExit(
            f"--plan-forecast {args.plan_forecast!r}: Preisprognosen und "
            "--forecast-price-strategy gehören zusammen (oder --skip-forecast)."
        )


def _backtesting_argv(args: argparse.Namespace, output_dir: str) -> list[str]:
    argv = ["--workers", str(args.workers), "--output-dir", output_dir]
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
    _validate_forecast_args(args)
    if args.start_month:
        _parse_month(args.start_month)
    if args.end_month:
        _parse_month(args.end_month)
    os.makedirs(args.output_dir, exist_ok=True)
    run_backtesting_main(_backtesting_argv(args, args.output_dir))
    forecast = None
    if not args.skip_forecast:
        forecast_dir = os.path.join(args.output_dir, FORECAST_SUBDIR)
        os.makedirs(forecast_dir, exist_ok=True)
        print(f"\nForecast-Modus: zweiter SE-Lauf nach {forecast_dir}")
        run_backtesting_main(_forecast_argv(args, forecast_dir))
        forecast = ForecastRun(*load_backtesting_log(forecast_dir))

    meta, hourly = load_backtesting_log(args.output_dir)
    if forecast is not None:
        assert_references_match(meta, hourly, forecast)
    period = meta["period"]
    start, end = pd.Timestamp(period["start"]), pd.Timestamp(period["end"])
    all_scenarios = scenarios_for_period(
        config.get_backtesting_scenarios(), start, end, period["horizon_mode"]
    )
    scenarios = {sid: all_scenarios[sid] for sid in meta["ladder_by_scenario"]}

    write_csv(
        daily_ladder_frame(meta, hourly, scenarios, forecast),
        os.path.join(args.output_dir, DAILY_CSV),
    )
    summary = summary_frame(meta, hourly, scenarios, forecast)
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
