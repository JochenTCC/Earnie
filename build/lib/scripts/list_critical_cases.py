"""Kritische Backtesting-Fälle aus backtesting_log.json ausgeben."""
from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from simulation.backtesting_log import (
    BACKTESTING_LOG_JSON,
    extract_critical_cases,
    load_backtesting_log,
    summarize_critical_cases,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Listet kritische Fälle aus backtesting_log.json.",
    )
    parser.add_argument(
        "--log-dir",
        default=".",
        help="Verzeichnis mit backtesting_log.json (Standard: aktuelles Verzeichnis).",
    )
    parser.add_argument(
        "--kind",
        action="append",
        metavar="KIND",
        help="Nur diese kind-Werte (z. B. consumption_tolerance, strict_slow).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Ausgabe als JSON-Array.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    meta, _ = load_backtesting_log(args.log_dir)
    cases = extract_critical_cases(meta)
    if args.kind:
        wanted = set(args.kind)
        cases = [c for c in cases if c.get("kind") in wanted]

    if args.json:
        print(json.dumps(cases, indent=2, ensure_ascii=False))
        return

    summary = summarize_critical_cases(cases)
    period = meta.get("period", {})
    print(
        f"Zeitraum {period.get('start')} – {period.get('end')} "
        f"({BACKTESTING_LOG_JSON})"
    )
    print(
        f"Kritische Einträge: {summary['total']} "
        f"({summary['distinct_windows']} Fenster mit Treffer)"
    )
    if summary["by_kind"]:
        kinds = ", ".join(f"{k}={v}" for k, v in sorted(summary["by_kind"].items()))
        print(f"Nach Art: {kinds}")
    print()
    for case in cases:
        kind = case.get("kind", "?")
        scenario = case.get("scenario_id", "?")
        anchor = case.get("window_anchor", "?")
        line = f"[{kind}] {scenario} @ {anchor}"
        if case.get("slot_datetime"):
            line += f" Slot={case['slot_datetime']}"
        if case.get("simulation_hour_index") is not None:
            line += f" h={case['simulation_hour_index']}"
        if kind == "consumption_tolerance":
            line += (
                f" Delta={case.get('diff_kwh', 0):.2f} kWh "
                f"(hist={case.get('historical_kwh', 0):.1f}, "
                f"opt={case.get('optimized_kwh', 0):.1f})"
            )
        elif case.get("strict_elapsed_sec") is not None:
            line += f" strict={case.get('strict_elapsed_sec'):.2f}s"
        eauto = (case.get("consumer_targets_kwh") or {}).get("eauto")
        if eauto is not None:
            line += f" eauto={float(eauto):.3f}kWh"
        print(line)


if __name__ == "__main__":
    main()
