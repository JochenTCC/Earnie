# run_backtesting.py
import os

# Backtesting braucht keine Loxone-Zugangsdaten aus der .env
os.environ["ENERGY_OPTIMIZER_OFFLINE"] = "1"

import argparse

import pandas as pd
import config
import profile_manager
from backtesting_log import save_backtesting_log
from data_loader import load_market_prices, resolve_simulation_window
from simulation_engine import (
    HISTORICAL_REFERENCE_ID,
    HistoricalDataCache,
    compute_historical_reference_costs,
    list_simulation_anchors,
    print_plausibility_report,
    run_simulation,
    window_anchor_for_date,
    window_slot_datetimes,
)

HISTORICAL_REFERENCE_LABEL = "Historisch (ohne Optimierung)"
BACKTESTING_YEAR = 2025
MONTH_ARG_HELP = f"Monatsnummer 1–12 (Basisjahr {BACKTESTING_YEAR})"


def _format_month_period(start: pd.Timestamp, end: pd.Timestamp) -> str:
    if start.month == end.month and start.year == end.year:
        return f"Monat {start.month}/{start.year}"
    return f"Monat {start.month}–{end.month}/{start.year}"


def _parse_month(value: str) -> pd.Timestamp:
    """Parst Monatsnummer 1–12 zum ersten Tag in BACKTESTING_YEAR."""
    try:
        month = int(value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Ungültiger Monat '{value}'. Erwartet wird {MONTH_ARG_HELP}."
        ) from exc
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError(
            f"Monat muss zwischen 1 und 12 liegen, nicht {value}."
        )
    return pd.Timestamp(BACKTESTING_YEAR, month, 1)


def resolve_backtesting_window(
    start_month: pd.Timestamp | None,
    end_month: pd.Timestamp | None,
    range_mode: str,
    cons_path: str,
    prod_path: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Ermittelt Start/Ende für die Simulation.
    Mit start_month/end_month: erster Tag des Startmonats bis letzter Tag des Endmonats.
    Ohne Angabe: wie bisher aus config (price_range / resolve_simulation_window).
    """
    if start_month is None and end_month is None:
        return resolve_simulation_window(range_mode, cons_path, prod_path)

    if start_month is None or end_month is None:
        raise SystemExit(
            "Bitte --start-month und --end-month gemeinsam angeben "
            f"({MONTH_ARG_HELP})."
        )

    start = start_month.normalize()
    end = (end_month + pd.offsets.MonthEnd(0)).normalize()

    if start > end:
        raise SystemExit(
            f"Startmonat ({start.month}) darf nicht nach Endmonat ({end_month.month}) liegen."
        )

    today = pd.Timestamp.now().normalize()
    end = min(end, today)

    lox_min, lox_max = profile_manager.get_loxone_date_bounds()
    if lox_min is not None:
        start = max(start, pd.Timestamp(lox_min))
    if lox_max is not None:
        end = min(end, pd.Timestamp(lox_max))

    if start > end:
        raise SystemExit(
            "Kein gültiger Schnitt zwischen gewähltem Monatszeitraum "
            "und verfügbaren Loxone-Logs."
        )

    return start, end


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backtesting der Energie-Optimierung auf historischen Loxone-Daten.",
    )
    parser.add_argument(
        "--start-month",
        type=_parse_month,
        metavar="MONAT",
        help=f"Erster Monat der Simulation (inkl.). {MONTH_ARG_HELP}",
    )
    parser.add_argument(
        "--end-month",
        type=_parse_month,
        metavar="MONAT",
        help=f"Letzter Monat der Simulation (inkl.). {MONTH_ARG_HELP}",
    )
    return parser


def _make_progress_printer(scenario_name: str):
    """Gibt eine Callback-Funktion für die Fortschrittsanzeige im Terminal zurück."""
    def progress(current: int, total: int) -> None:
        pct = 100 * current / total
        bar_width = 30
        filled = int(bar_width * current / total)
        bar = "#" * filled + "-" * (bar_width - filled)
        print(
            f"\r  [{bar}] {pct:5.1f}% ({current}/{total} h) – {scenario_name}",
            end="",
            flush=True,
        )
        if current == total:
            print()
    return progress


def _all_labels(scenario_labels: dict[str, str]) -> dict[str, str]:
    labels = {HISTORICAL_REFERENCE_ID: HISTORICAL_REFERENCE_LABEL}
    labels.update(scenario_labels)
    return labels


def print_monthly_report(results, labels: dict[str, str]):
    """Erstellt den monatlichen tabellarischen Vergleich im Terminal."""
    report_df = pd.DataFrame()
    ref_label = labels.get(HISTORICAL_REFERENCE_ID, HISTORICAL_REFERENCE_ID)
    baseline_id = "runtime_settings"
    baseline_label = labels.get(baseline_id, baseline_id)

    for name, df in results.items():
        report_df[labels.get(name, name)] = df["sim_cost"].resample("ME").sum()

    formatters = {col: "{:,.2f} €".format for col in report_df.columns}
    if ref_label in report_df.columns:
        for col in report_df.columns:
            if col == ref_label:
                continue
            savings_col = f"Einsparung vs {col}"
            report_df[savings_col] = report_df[ref_label] - report_df[col]
            formatters[savings_col] = "{:,.2f} €".format

    print("\n=== MONATLICHER SIMULATIONS-VERGLEICH ===")
    print(report_df.to_string(formatters=formatters))
    if ref_label in report_df.columns and baseline_label in report_df.columns:
        print(
            f"(Einsparung vs '{ref_label}' = Nutzen der Optimierung gegenüber "
            "historischem Verbrauch ohne Steuerung)"
        )
    print("=======================================================")


def print_total_summary(results, labels: dict[str, str]):
    """Gibt die Gesamtkosten und Einsparung über den gesamten Zeitraum aus."""
    ref_id = HISTORICAL_REFERENCE_ID
    ref_total = results[ref_id]["sim_cost"].sum() if ref_id in results else None
    baseline_id = "runtime_settings"
    runtime_total = results[baseline_id]["sim_cost"].sum() if baseline_id in results else None

    print("\n=== GESAMTSUMME (gesamter Simulationszeitraum) ===")
    for name, df in results.items():
        total = df["sim_cost"].sum()
        display = labels.get(name, name)
        if name == ref_id:
            print(f"  {display:30s}: {total:>10,.2f} €  (Referenz, keine Optimierung)")
        elif name == baseline_id:
            if ref_total is not None:
                savings = ref_total - total
                print(
                    f"  {display:30s}: {total:>10,.2f} €  "
                    f"(Einsparung vs Referenz: {savings:>+10,.2f} €)"
                )
            else:
                print(f"  {display:30s}: {total:>10,.2f} €  (Baseline)")
        elif ref_total is not None:
            savings = ref_total - total
            print(
                f"  {display:30s}: {total:>10,.2f} €  "
                f"(Einsparung vs Referenz: {savings:>+10,.2f} €)"
            )
        elif runtime_total is not None and name != baseline_id:
            savings = runtime_total - total
            print(f"  {display:30s}: {total:>10,.2f} €  (Einsparung vs Baseline: {savings:>+10,.2f} €)")
        else:
            print(f"  {display:30s}: {total:>10,.2f} €")
    print("================================================")


def main(argv: list[str] | None = None):
    args = _build_arg_parser().parse_args(argv)

    sim_cfg = config.get_file_paths_battery_simulation()
    range_mode = sim_cfg.get("price_range", "last_12_months")
    price_source = sim_cfg.get("price_source", "csv")

    start, end = resolve_backtesting_window(
        args.start_month,
        args.end_month,
        range_mode,
        sim_cfg["path_consumption"],
        sim_cfg["path_production"],
    )

    if args.start_month is not None:
        print(
            f"Gewählter Zeitraum: {_format_month_period(start, end)} "
            f"({start.date()} – {end.date()})"
        )
    else:
        print(
            f"Standard-Zeitraum aus config ({range_mode}): "
            f"{start.date()} – {end.date()}"
        )

    print("Lade historische Verbrauchsdaten (Loxone-Logs)...")
    cache = HistoricalDataCache()
    cache.load()
    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise SystemExit(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )

    if price_source == "api":
        provider = sim_cfg.get("price_provider", "awattar")
        print(f"Lade Börsenpreise per API ({provider}) für {start.date()} bis {end.date()}...")
    else:
        print(f"Lade Börsenpreise aus CSV für {start.date()} bis {end.date()}...")

    prices = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )

    first_window = window_slot_datetimes(anchors[0])[0]
    last_window = window_slot_datetimes(anchors[-1])[-1]
    ready_h = window_anchor_for_date(anchors[-1].date()).strftime("%H:%M")
    print(
        f"Simulationszeitraum: {first_window.date()} bis {last_window.date()} "
        f"({len(anchors)} x 24h-Fenster, {len(anchors) * 24} Stunden)"
    )
    print(
        "Modus: tagweise Optimierung (Batterie + flexible Verbraucher), "
        f"24h-Fenster endend um ready_by_hour (z. B. {ready_h})"
    )

    k_push = config.get_push_price_cent()
    scenario_labels = config.get_scenario_labels()
    labels = _all_labels(scenario_labels)

    print(f"Berechne Referenz '{HISTORICAL_REFERENCE_LABEL}'...")
    sim_results = {
        HISTORICAL_REFERENCE_ID: compute_historical_reference_costs(
            start, end, prices, k_push, cache=cache
        ),
    }
    plausibility_by_scenario: dict = {}

    scenarios = config.get_backtesting_scenarios()
    for name, params in scenarios.items():
        display = labels.get(name, name)
        print(f"Simuliere Szenario: '{display}'...")
        df_result, plausibility = run_simulation(
            start,
            end,
            params,
            prices,
            cache=cache,
            on_progress=_make_progress_printer(display),
        )
        sim_results[name] = df_result
        plausibility_by_scenario[name] = plausibility
        print_plausibility_report(plausibility)

    print_monthly_report(sim_results, labels)
    print_total_summary(sim_results, labels)

    period_meta = {
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "windows": len(anchors),
        "start_month": args.start_month.month if args.start_month is not None else None,
        "end_month": args.end_month.month if args.end_month is not None else None,
        "backtesting_year": BACKTESTING_YEAR,
        "price_source": price_source,
    }
    log_path = save_backtesting_log(
        sim_results,
        labels,
        plausibility_by_scenario,
        period_meta,
    )
    print(f"\nBacktesting-Log gespeichert: {log_path}")


if __name__ == "__main__":
    main()
