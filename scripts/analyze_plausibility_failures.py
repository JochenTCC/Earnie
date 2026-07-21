"""Plausibilitäts-Warnungen aus backtesting_log.json pro Fenster aufschlüsseln."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pandas as pd

_BACKTESTING_LOG_JSON = "backtesting_log.json"
_SIDECAR_ENV_MAP = (
    ("COMPONENTS_PATH", "components.json"),
    ("HOUSE_PROFILES_PATH", "house_profiles.json"),
    ("TARIFFS_PATH", "tariffs.json"),
    ("BACKTESTING_SCENARIOS_PATH", "backtesting_scenarios.json"),
)


def _parse_window_end(value: str) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.to_pydatetime()


def _infer_stack_from_log(log_path: Path) -> tuple[Path | None, Path | None]:
    """z. B. greenfield/runtime/backtesting_log.json → greenfield/config + runtime."""
    runtime_dir = log_path.resolve().parent
    config_dir = runtime_dir.parent / "config"
    if (config_dir / "config.json").is_file():
        return config_dir, runtime_dir
    return None, None


def _apply_stack_env(config_dir: Path, runtime_dir: Path | None) -> None:
    config_dir = config_dir.resolve()
    os.environ["EARNIE_CONFIG_PATH"] = str(config_dir / "config.json")
    if runtime_dir is not None:
        os.environ["EARNIE_RUNTIME_PATH"] = str(runtime_dir.resolve())
    dotenv = config_dir / ".env"
    if dotenv.is_file():
        os.environ["EARNIE_DOTENV_PATH"] = str(dotenv)
    for env_suffix, filename in _SIDECAR_ENV_MAP:
        sidecar = config_dir / filename
        if sidecar.is_file():
            os.environ[f"EARNIE_{env_suffix}"] = str(sidecar)


def _bootstrap_config(
    *,
    config_dir: Path | None,
    runtime_dir: Path | None,
    log_path: Path,
) -> ModuleType:
    os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")
    if config_dir is not None:
        _apply_stack_env(config_dir, runtime_dir)
    elif not os.environ.get("EARNIE_CONFIG_PATH") and not os.environ.get(
        "ENERGY_OPTIMIZER_CONFIG_PATH"
    ):
        inferred_config, inferred_runtime = _infer_stack_from_log(log_path)
        if inferred_config is not None:
            _apply_stack_env(inferred_config, inferred_runtime or log_path.parent)
            print(
                f"Config-Stack aus Log-Pfad abgeleitet: {inferred_config}",
                file=sys.stderr,
            )
    from runtime_store.config_load import load_config_or_exit

    return load_config_or_exit()


def _load_failures(log_path: Path, scenario_id: str) -> list[dict]:
    from simulation.backtesting_log import load_backtesting_log

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


def _scenario_params(config: ModuleType, scenario_id: str) -> dict:
    scenarios = config.get_backtesting_scenarios()
    if scenario_id not in scenarios:
        known = ", ".join(sorted(scenarios))
        raise SystemExit(
            f"Szenario '{scenario_id}' nicht gefunden. "
            f"Verfügbar: {known or '(keine)'}"
        )
    return dict(scenarios[scenario_id])


def _flex_delta_table(
    config: ModuleType,
    historical_totals: dict[str, float],
    delivered: dict[str, float],
    flexible_consumers: list | None,
) -> list[tuple[str, float, float, float]]:
    rows: list[tuple[str, float, float, float]] = []
    consumers = flexible_consumers or config.get_flexible_consumers(optimizer_only=True)
    for consumer in consumers:
        cid = consumer["id"]
        hist = float(historical_totals.get(cid, 0.0))
        opt = float(delivered.get(cid, 0.0))
        rows.append((cid, hist, opt, round(opt - hist, 3)))
    return rows


def _simulate_failure_window(
    config: ModuleType,
    anchor: datetime,
    cache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
) -> tuple[list[dict], dict]:
    from simulation.engine import (
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
        build_historical_window_matrix,
        simulate_horizon,
    )

    feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
    matrix, meta = build_historical_window_matrix(
        anchor,
        cache,
        prices_df,
        feed_in_settings=feed_in,
        scenario_params=scenario_params,
    )
    flexible_consumers = _flexible_consumers_from_scenario(scenario_params)
    battery_params = _scenario_to_battery_params(scenario_params)
    chart_rows = simulate_horizon(
        matrix,
        initial_soc=50.0,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        flexible_consumers=flexible_consumers,
    )
    return chart_rows, meta


def analyze_failure(
    config: ModuleType,
    failure: dict,
    *,
    cache,
    anchors: list[datetime],
    prices_df: pd.DataFrame,
    scenario_params: dict,
) -> dict:
    from optimizer.simulation import (
        delivered_flex_kwh_from_rows,
        total_consumption_kwh_from_rows,
    )

    window_end = _parse_window_end(failure["window_end"])
    anchor = _find_anchor(anchors, window_end)
    if anchor is None:
        return {
            "window_end": failure["window_end"],
            "error": "Anker nicht in Simulationsfenstern gefunden",
        }

    chart_rows, meta = _simulate_failure_window(
        config, anchor, cache, prices_df, scenario_params
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
    flex_table = _flex_delta_table(
        config,
        meta["historical_totals"],
        delivered,
        flex_consumers,
    )
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
        print(
            f"  Grundlast: {item['baseload_kwh']:.2f} kWh "
            f"(hist {item['historical_baseload_kwh']:.2f}, "
            f"Δ {item['baseload_delta_kwh']:+.2f})"
        )
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


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plausibilitäts-Warnungen aus backtesting_log.json aufschlüsseln."
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(_BACKTESTING_LOG_JSON),
        help="Pfad zu backtesting_log.json",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Config-Ordner (config.json + components.json + Sidecars); "
        "sonst aus --log abgeleitet (z. B. greenfield/config)",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=None,
        help="Runtime-Ordner (cons_data, backtesting_log); Standard: Parent von --log",
    )
    parser.add_argument(
        "--scenario",
        default="live",
        help="Szenario-ID in meta.plausibility (aufgelöst via components.json)",
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
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_arg_parser().parse_args(argv)
    runtime_dir = args.runtime_dir
    if runtime_dir is None and args.log.is_file():
        runtime_dir = args.log.parent

    config = _bootstrap_config(
        config_dir=args.config_dir,
        runtime_dir=runtime_dir,
        log_path=args.log,
    )

    from data.data_loader import load_market_prices
    from scripts.run_backtesting import resolve_backtesting_window
    from simulation.backtesting_log import load_backtesting_log
    from simulation.engine import HistoricalDataCache, list_simulation_anchors

    failures = _load_failures(args.log, args.scenario)
    if args.limit > 0:
        failures = failures[: args.limit]

    sim_cfg = config.get_scenario_explorer_conf()
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
    scenario_params = _scenario_params(config, args.scenario)

    results = [
        analyze_failure(
            config,
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
