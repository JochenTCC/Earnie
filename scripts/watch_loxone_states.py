#!/usr/bin/env python3
"""Watchdog: Loxone-Steuerwerte gegen main.py-Vorgabe prüfen und bei Abweichung korrigieren.

Aufruf: python -m scripts.watch_loxone_states [--once] [--interval-sec 60]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import logger_config
from integrations.loxone_watchdog import run_watchdog_cycle

DEFAULT_INTERVAL_SEC = 60
DEFAULT_LOG_FILE = os.path.join(
    os.environ.get("ENERGY_OPTIMIZER_RUNTIME_DIR", "runtime"),
    "loxone_watchdog.log",
)


def _log_mismatches(mismatches: list) -> None:
    log = logging.getLogger("loxone_watchdog")
    for item in mismatches:
        if item.read_failed:
            log.error(
                "Loxone-Merker '%s': Lesen fehlgeschlagen (Soll: %s) – keine Korrektur",
                item.io_name,
                item.expected,
            )
            continue
        if item.corrected:
            log.error(
                "Abweichung '%s': Soll %s, Ist %s → auf Soll korrigiert",
                item.io_name,
                item.expected,
                item.actual,
            )
        else:
            log.error(
                "Abweichung '%s': Soll %s, Ist %s → Korrektur fehlgeschlagen",
                item.io_name,
                item.expected,
                item.actual,
            )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prüft in festen Abständen, ob Loxone-Steuer-Merker noch dem letzten "
            "main.py-Durchlauf entsprechen, und setzt Abweichungen zurück."
        )
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=DEFAULT_INTERVAL_SEC,
        help=f"Prüfintervall in Sekunden (Standard: {DEFAULT_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_FILE,
        help=f"Log-Datei für Fehlereinträge (Standard: {DEFAULT_LOG_FILE})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Nur einen Prüfdurchlauf, dann beenden",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.interval_sec < 1:
        print("--interval-sec muss mindestens 1 sein", file=sys.stderr)
        return 2

    logger_config.setup_logging(log_file=args.log_file, level=logging.INFO)
    log = logging.getLogger("loxone_watchdog")
    log.info(
        "Loxone-Watchdog gestartet (Intervall %s s, Log: %s)",
        args.interval_sec,
        args.log_file,
    )

    while True:
        try:
            mismatches = run_watchdog_cycle()
            if mismatches:
                _log_mismatches(mismatches)
            else:
                log.debug("Alle Steuer-Merker stimmen mit main.py überein")
        except Exception:
            log.exception("Unerwarteter Fehler im Watchdog-Durchlauf")

        if args.once:
            return 0
        time.sleep(args.interval_sec)


if __name__ == "__main__":
    raise SystemExit(main())
