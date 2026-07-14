# scripts/run_backtesting.py
import os

if __name__ == "__main__":
    # Nur im Backtesting-Prozess — nicht beim Import aus der Streamlit-UI setzen.
    os.environ["ENERGY_OPTIMIZER_OFFLINE"] = "1"

import argparse
import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
import logger_config
from data import profile_manager
from simulation.backtesting_log import save_backtesting_log
from simulation.backtesting_log import build_critical_cases, summarize_critical_cases
from data.data_loader import load_market_prices, resolve_simulation_window
from data.backtesting_prices import (
    MISSING_PRICE_STRATEGY_FORECAST,
    PRICE_STRATEGY_PERFECT,
    VALID_PRICE_STRATEGIES,
    load_price_resources,
    parse_price_strategy,
)
from house_config.entity_resolution import strip_assets_for_reference
from simulation.engine import (
    HISTORICAL_REFERENCE_ID,
    HistoricalDataCache,
    build_per_scenario_reference_costs,
    compute_historical_reference_costs,
    list_simulation_anchors,
    print_plausibility_report,
    run_simulation,
    window_anchor_for_date,
    window_slot_datetimes,
)
from simulation.backtesting_progress import (
    clear_progress_dir,
    prepare_progress_dir,
    worker_progress_path,
)
from simulation.horizon_mode import (
    DEFAULT_HORIZON_MODE,
    FIXED_24H,
    SUNRISE_WINDOW,
    parse_horizon_mode,
)

HISTORICAL_REFERENCE_LABEL = "Historisch (ohne Optimierung, ohne PV/Batterie)"
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

    lox_min, lox_max = profile_manager.get_cons_data_date_bounds()
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


def _price_load_window(
    start: pd.Timestamp,
    end: pd.Timestamp,
    price_strategy: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Erweitert den Preisabruf für Spiegelung/Prognose (Lookback + 24h-Fenster vor start)."""
    if price_strategy == PRICE_STRATEGY_PERFECT:
        return start, end
    from data.market_prices import MAX_MIRROR_LOOKBACK_DAYS

    load_start = (start - pd.Timedelta(days=MAX_MIRROR_LOOKBACK_DAYS + 1)).normalize()
    return load_start, end


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
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Parallele Worker für Szenario-Simulationen (Standard: 1, sequentiell).",
    )
    parser.add_argument(
        "--horizon-mode",
        choices=[FIXED_24H, SUNRISE_WINDOW],
        default=DEFAULT_HORIZON_MODE,
        help=(
            "Planungshorizont für die Optimierung: "
            f"'{FIXED_24H}' (24h/E-Auto-Anker, Standard) oder "
            f"'{SUNRISE_WINDOW}' (Jetzt→SA₂, SOC_min am Sonnenaufgang)."
        ),
    )
    parser.add_argument(
        "--log-file",
        metavar="PFAD",
        help=(
            "Zusätzliche UTF-8-Logdatei (empfohlen: backtesting_logs/lauf.log; "
            "nicht Shell-Umleitung unter Windows)."
        ),
    )
    parser.add_argument(
        "--price-strategy",
        choices=list(VALID_PRICE_STRATEGIES),
        default=PRICE_STRATEGY_PERFECT,
        help=(
            "Preise in der grünen Zone (nur sunrise_window): "
            "'perfect' = historischer Ist-Preis (Standard), "
            "'mirror' = Spiegelung, 'forecast' = OLS-Prognose."
        ),
    )
    parser.add_argument(
        "--feature-dataset",
        metavar="CSV",
        help="Training-CSV für price_strategy=forecast (Standard: neuestes data/cache/price_training_*.csv).",
    )
    parser.add_argument(
        "--forecast-model",
        metavar="JSON",
        help="OLS-Koeffizienten für price_strategy=forecast (Standard: market_prices.forecast_model_path).",
    )
    parser.add_argument(
        "--output-dir",
        metavar="PFAD",
        default=".",
        help="Zielordner für backtesting_log.json und backtesting_hourly.csv (Standard: .).",
    )
    parser.add_argument(
        "--progress-file",
        metavar="PFAD",
        help=(
            "Fortschrittsverzeichnis für UI (pro Worker eine JSON-Datei); "
            "Legacy: einzelne *.json-Datei → Sibling .backtesting_workers/."
        ),
    )
    return parser


def _default_feature_dataset() -> Path:
    cache = Path("data/cache")
    candidates = sorted(cache.glob("price_training_*.csv"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit(
            "Kein price_training_*.csv in data/cache — "
            "python -m scripts.build_price_training_dataset ausführen."
        )
    return candidates[-1]


def _default_forecast_model() -> Path:
    from data.price_forecast_live import get_forecast_model_path

    return get_forecast_model_path()


def _resolve_price_paths(args) -> tuple[Path | None, Path | None]:
    strategy = parse_price_strategy(args.price_strategy)
    if strategy != MISSING_PRICE_STRATEGY_FORECAST:
        return None, None
    dataset = Path(args.feature_dataset) if args.feature_dataset else _default_feature_dataset()
    model = Path(args.forecast_model) if args.forecast_model else _default_forecast_model()
    return dataset, model


def _run_scenario_worker(
    name: str,
    params: dict,
    start_iso: str,
    end_iso: str,
    prices: pd.DataFrame,
    horizon_mode: str,
    price_strategy: str,
    feature_dataset_path: str | None,
    forecast_model_path: str | None,
    progress_file: str | None = None,
    progress_label: str | None = None,
) -> tuple[str, pd.DataFrame, object, list[dict], list[dict]]:
    """Top-Level-Worker für ProcessPoolExecutor (Windows spawn)."""
    from pathlib import Path

    from simulation.engine import run_simulation, HistoricalDataCache

    start = pd.Timestamp(start_iso)
    end = pd.Timestamp(end_iso)
    cache = HistoricalDataCache()
    cache.load()
    price_resources = load_price_resources(
        price_strategy,
        feature_dataset_path=Path(feature_dataset_path) if feature_dataset_path else None,
        forecast_model_path=Path(forecast_model_path) if forecast_model_path else None,
    )
    snapshots: list[dict] = []
    display = progress_label or name
    worker_path = worker_progress_path(progress_file, name)
    on_progress = (
        _make_progress_printer(display, worker_path) if worker_path else None
    )
    df_result, plausibility, cbc_events = run_simulation(
        start,
        end,
        params,
        prices,
        cache=cache,
        scenario_id=name,
        horizon_mode=horizon_mode,
        price_resources=price_resources,
        snapshot_collector=snapshots,
        on_progress=on_progress,
    )
    return name, df_result, plausibility, cbc_events, snapshots


def _run_scenarios_parallel(
    scenarios: dict[str, dict],
    labels: dict[str, str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    prices: pd.DataFrame,
    workers: int,
    horizon_mode: str,
    price_strategy: str,
    feature_dataset_path: str | None,
    forecast_model_path: str | None,
    progress_file: str | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, object], dict[str, list[dict]], list[dict]]:
    sim_results: dict[str, pd.DataFrame] = {}
    plausibility_by_scenario: dict[str, object] = {}
    cbc_events_by_scenario: dict[str, list[dict]] = {}
    window_snapshots: list[dict] = []
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    print(f"Simuliere {len(scenarios)} Szenarien parallel ({workers} Worker)...")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_scenario_worker,
                name,
                dict(params),
                start_iso,
                end_iso,
                prices,
                horizon_mode,
                price_strategy,
                feature_dataset_path,
                forecast_model_path,
                progress_file,
                labels.get(name, name),
            ): name
            for name, params in scenarios.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            display = labels.get(name, name)
            try:
                result_name, df_result, plausibility, cbc_events, snapshots = future.result()
            except Exception as exc:
                raise RuntimeError(
                    f"Szenario '{display}' ({name}) fehlgeschlagen: {exc}"
                ) from exc
            sim_results[result_name] = df_result
            plausibility_by_scenario[result_name] = plausibility
            cbc_events_by_scenario[result_name] = cbc_events
            window_snapshots.extend(snapshots)
            print(f"  Fertig: {display}")
    return sim_results, plausibility_by_scenario, cbc_events_by_scenario, window_snapshots


_PROGRESS_WRITE_MIN_INTERVAL_SEC = 1.0
_PROGRESS_REPLACE_RETRIES = 3
_PROGRESS_REPLACE_RETRY_DELAY_SEC = 0.05


def _atomic_replace_unavailable(exc: OSError) -> bool:
    """True wenn tmp→Ziel nicht atomar ersetzt werden kann (Windows/SMB/UNC)."""
    if getattr(exc, "errno", None) in (13, 16):
        return True
    return getattr(exc, "winerror", None) == 5


def _write_progress_file(path: str | None, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        for attempt in range(_PROGRESS_REPLACE_RETRIES):
            try:
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(target)
                return
            except OSError as exc:
                if not _atomic_replace_unavailable(exc):
                    raise
                if attempt + 1 < _PROGRESS_REPLACE_RETRIES:
                    time.sleep(_PROGRESS_REPLACE_RETRY_DELAY_SEC)
                    continue
                target.write_text(content, encoding="utf-8")
                return
    finally:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass


def _make_progress_printer(scenario_name: str, progress_file: str | None = None):
    """Gibt eine Callback-Funktion für die Fortschrittsanzeige im Terminal zurück."""
    last_write_at = 0.0
    last_written_current = -1

    def progress(current: int, total: int) -> None:
        nonlocal last_write_at, last_written_current
        pct = 100 * current / total if total else 0.0
        bar_width = 30
        filled = int(bar_width * current / total) if total else 0
        bar = "#" * filled + "-" * (bar_width - filled)
        print(
            f"\r  [{bar}] {pct:5.1f}% ({current}/{total} h) – {scenario_name}",
            end="",
            flush=True,
        )
        if current == total:
            print()
        if not progress_file:
            return
        now = time.monotonic()
        if (
            current != total
            and current == last_written_current
            and now - last_write_at < _PROGRESS_WRITE_MIN_INTERVAL_SEC
        ):
            return
        _write_progress_file(
            progress_file,
            {
                "current": current,
                "total": total,
                "scenario": scenario_name,
                "phase": "simulation",
            },
        )
        last_write_at = now
        last_written_current = current

    return progress


def _all_labels(scenario_labels: dict[str, str]) -> dict[str, str]:
    labels = {HISTORICAL_REFERENCE_ID: HISTORICAL_REFERENCE_LABEL}
    labels.update(scenario_labels)
    return labels


def _print_cbc_events_summary(cbc_events_by_scenario: dict[str, list[dict]], labels: dict[str, str]) -> None:
    total = sum(len(events) for events in cbc_events_by_scenario.values())
    if total == 0:
        print("\nCBC-Ereignisse: keine (Strict innerhalb Limit und optimal).")
        return
    print(f"\n=== CBC-Ereignisse ({total} gesamt, siehe backtesting_cbc_events.jsonl) ===")
    for scenario_id, events in cbc_events_by_scenario.items():
        display = labels.get(scenario_id, scenario_id)
        counts: dict[str, int] = {}
        for event in events:
            kind = str(event.get("event", "?"))
            counts[kind] = counts.get(kind, 0) + 1
        parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"  {display}: {parts}")
        for event in events[:5]:
            anchor = event.get("window_anchor", "?")
            slot = event.get("slot_datetime", "?")
            hour = event.get("simulation_hour_index", "?")
            kind = event.get("event", "?")
            elapsed = event.get("strict_elapsed_sec")
            elapsed_txt = f", {elapsed:.2f}s" if elapsed is not None else ""
            print(f"    [{kind}] h={hour} Anker={anchor} Slot={slot}{elapsed_txt}")
        if len(events) > 5:
            print(f"    ... und {len(events) - 5} weitere")
    print("====================================================")


def print_monthly_report(results, labels: dict[str, str]):
    """Erstellt den monatlichen tabellarischen Vergleich im Terminal."""
    report_df = pd.DataFrame()
    ref_label = labels.get(HISTORICAL_REFERENCE_ID, HISTORICAL_REFERENCE_ID)
    baseline_id = config.get_live_scenario_id()
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
    baseline_id = config.get_live_scenario_id()
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
    logger_config.configure_utf8_stdio()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    from house_config.tariff_plausibility import (
        collect_tariff_plausibility_errors,
        format_tariff_plausibility_errors,
    )
    from runtime_store.persist_paths import (
        resolve_backtesting_scenarios_json_path,
        resolve_tariffs_json_path,
        resolve_tariffs_schema_template_path,
    )

    tariff_errors = collect_tariff_plausibility_errors(
        tariffs_path=resolve_tariffs_json_path(),
        scenarios_path=resolve_backtesting_scenarios_json_path(),
        schema_path=resolve_tariffs_schema_template_path(),
    )
    if tariff_errors:
        raise SystemExit(format_tariff_plausibility_errors(tariff_errors))

    args = _build_arg_parser().parse_args(argv)
    horizon_mode = parse_horizon_mode(args.horizon_mode)
    price_strategy = parse_price_strategy(args.price_strategy)
    if price_strategy != PRICE_STRATEGY_PERFECT and horizon_mode != SUNRISE_WINDOW:
        raise SystemExit(
            f"--price-strategy {price_strategy} erfordert --horizon-mode {SUNRISE_WINDOW}."
        )
    feature_dataset_path, forecast_model_path = _resolve_price_paths(args)
    feature_dataset_str = str(feature_dataset_path) if feature_dataset_path else None
    forecast_model_str = str(forecast_model_path) if forecast_model_path else None
    price_resources = load_price_resources(
        price_strategy,
        feature_dataset_path=feature_dataset_path,
        forecast_model_path=forecast_model_path,
    )
    if args.log_file:
        logger_config.attach_utf8_log_file(args.log_file)
    if args.workers < 1:
        raise SystemExit("--workers muss >= 1 sein.")

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

    if price_strategy != PRICE_STRATEGY_PERFECT:
        print(f"Preisstrategie grüne Zone: {price_strategy}")
        if feature_dataset_path is not None:
            print(f"  Feature-Dataset: {feature_dataset_path}")
        if forecast_model_path is not None:
            print(f"  Prognosemodell: {forecast_model_path}")

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
        price_load_start, price_load_end = _price_load_window(start, end, price_strategy)
        if price_load_start < start:
            print(
                f"Lade Börsenpreise per API ({provider}) für {price_load_start.date()} "
                f"bis {price_load_end.date()} (Simulation {start.date()}–{end.date()}, "
                f"+{ (start - price_load_start).days}d Lookback für {price_strategy})..."
            )
        else:
            print(
                f"Lade Börsenpreise per API ({provider}) für {start.date()} bis {end.date()}..."
            )
    else:
        price_load_start, price_load_end = _price_load_window(start, end, price_strategy)
        if price_load_start < start:
            print(
                f"Lade Börsenpreise aus CSV für {price_load_start.date()} bis "
                f"{price_load_end.date()} (+Lookback für {price_strategy})..."
            )
        else:
            print(f"Lade Börsenpreise aus CSV für {start.date()} bis {end.date()}...")

    prices = load_market_prices(
        price_load_start,
        price_load_end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )

    first_window = window_slot_datetimes(anchors[0])[0]
    last_window = window_slot_datetimes(anchors[-1])[-1]
    ready_h = window_anchor_for_date(anchors[-1].date()).strftime("%H:%M")
    print(
        f"Simulationszeitraum: {first_window.date()} bis {last_window.date()} "
        f"({len(anchors)} x 24h-Schritte, {len(anchors) * 24} Stunden Output)"
    )
    print(
        "Modus: tagweise Optimierung (Batterie + flexible Verbraucher), "
        f"horizon_mode={horizon_mode}"
    )
    if horizon_mode == FIXED_24H:
        print(
            f"  {len(anchors)} x 24h-Fenster endend um ready_by_hour (z. B. {ready_h})"
        )
    else:
        print(
            f"  {len(anchors)} Schritte à 24h Output; MILP Jetzt→SA₂ pro Schritt "
            f"(SOC_min am Sonnenaufgang)"
        )

    ref_settings = config.get_backtesting_feed_in_settings()
    scenario_labels = config.get_scenario_labels()
    labels = _all_labels(scenario_labels)
    scenarios = config.get_backtesting_scenarios()
    live_scenario_id = config.get_live_scenario_id()
    live_params = scenarios.get(live_scenario_id) or (
        next(iter(scenarios.values())) if scenarios else None
    )
    if live_params is not None:
        ref_settings = config.get_backtesting_feed_in_settings(
            runtime_override=live_params
        )
    reference_params = (
        strip_assets_for_reference(live_params) if live_params is not None else None
    )
    progress_file = args.progress_file
    total_hours = len(anchors) * 24

    if progress_file:
        prepare_progress_dir(progress_file)
        _write_progress_file(
            worker_progress_path(progress_file, "_reference"),
            {
                "current": 0,
                "total": total_hours,
                "scenario": HISTORICAL_REFERENCE_LABEL,
                "phase": "reference",
            },
        )

    print(f"Berechne Referenz '{HISTORICAL_REFERENCE_LABEL}'...")
    sim_results = {
        HISTORICAL_REFERENCE_ID: compute_historical_reference_costs(
            start,
            end,
            prices,
            ref_settings,
            cache=cache,
            scenario_params=reference_params,
        ),
    }
    extra_refs, extra_ref_labels, reference_by_scenario = (
        build_per_scenario_reference_costs(
            start,
            end,
            prices,
            cache,
            scenarios,
            live_scenario_id=live_scenario_id,
            scenario_labels=scenario_labels,
        )
    )
    sim_results.update(extra_refs)
    labels.update(extra_ref_labels)
    plausibility_by_scenario: dict = {}
    cbc_events_by_scenario: dict[str, list[dict]] = {}
    window_snapshots: list[dict] = []

    if args.workers == 1:
        for name, params in scenarios.items():
            display = labels.get(name, name)
            print(f"Simuliere Szenario: '{display}'...")
            scenario_snapshots: list[dict] = []
            df_result, plausibility, cbc_events = run_simulation(
                start,
                end,
                params,
                prices,
                cache=cache,
                on_progress=_make_progress_printer(
                    display,
                    worker_progress_path(progress_file, name),
                ),
                scenario_id=name,
                horizon_mode=horizon_mode,
                price_resources=price_resources,
                snapshot_collector=scenario_snapshots,
            )
            sim_results[name] = df_result
            plausibility_by_scenario[name] = plausibility
            cbc_events_by_scenario[name] = cbc_events
            window_snapshots.extend(scenario_snapshots)
            print_plausibility_report(plausibility)
    else:
        parallel_results, parallel_plausibility, parallel_cbc, parallel_snapshots = (
            _run_scenarios_parallel(
            scenarios,
            labels,
            start,
            end,
            prices,
            args.workers,
            horizon_mode,
            price_strategy,
            feature_dataset_str,
            forecast_model_str,
            progress_file=progress_file,
        )
        )
        sim_results.update(parallel_results)
        plausibility_by_scenario.update(parallel_plausibility)
        cbc_events_by_scenario.update(parallel_cbc)
        window_snapshots.extend(parallel_snapshots)
        for name in scenarios:
            print_plausibility_report(plausibility_by_scenario[name])

    _print_cbc_events_summary(cbc_events_by_scenario, labels)

    critical_cases = build_critical_cases(
        plausibility_by_scenario,
        cbc_events_by_scenario,
    )
    if critical_cases:
        summary = summarize_critical_cases(critical_cases)
        print(
            f"\nKritische Fälle gesamt: {summary['total']} "
            f"({summary['distinct_windows']} Fenster) – siehe critical_cases in backtesting_log.json"
        )

    print_monthly_report(sim_results, labels)
    print_total_summary(sim_results, labels)

    period_meta = {
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "windows": len(anchors),
        "horizon_mode": horizon_mode,
        "start_month": args.start_month.month if args.start_month is not None else None,
        "end_month": args.end_month.month if args.end_month is not None else None,
        "backtesting_year": BACKTESTING_YEAR,
        "price_source": price_source,
        "price_strategy": price_strategy,
        "reference_by_scenario": reference_by_scenario,
    }
    log_path = save_backtesting_log(
        sim_results,
        labels,
        plausibility_by_scenario,
        period_meta,
        log_dir=args.output_dir,
        cbc_events_by_scenario=cbc_events_by_scenario,
        window_snapshots=window_snapshots,
    )
    if progress_file:
        clear_progress_dir(progress_file)
    print(f"\nBacktesting-Log gespeichert: {log_path}")


if __name__ == "__main__":
    main()
