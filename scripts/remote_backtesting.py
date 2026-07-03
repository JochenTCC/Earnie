#!/usr/bin/env python3
"""
remote_backtesting.py – Backtesting auf einem leistungsstärkeren PC im LAN.

Gemeinsame Datenbasis (empfohlen): SMB-Freigabe auf NAS/Server, z. B.
  \\\\NAS\\EnergyOptimizer\\backtesting-sync\\
    config\\           ← config.json, backtesting_scenarios.json
    runtime\\          ← cons_data_hourly.csv
    Historical-Data\\   ← Loxone-CSVs (wie in config.json referenziert)
    results\\          ← backtesting_log.json, backtesting_hourly.csv

Einrichtung:
  1. Freigabe anlegen und von beiden PCs aus erreichbar machen
  2. config/remote_backtesting.example.json → config/remote_backtesting.json
  3. Auf dem Remote-PC: Repo klonen, Python-Abhängigkeiten installieren
  4. SSH-Schlüssel für passwortlosen Login einrichten

Aufruf (von diesem PC):
  python -m scripts.remote_backtesting push
  python -m scripts.remote_backtesting run -- --start-month 6 --end-month 7
  python -m scripts.remote_backtesting pull
  python -m scripts.remote_backtesting sync-run -- --start-month 6 --end-month 7

Unterbefehle:
  push      Lokale Sync-Dateien → Share
  pull      Share/results → Repo-Root (für Streamlit-UI)
  run       Remote: Share → Repo, run_backtesting, Ergebnisse → Share
  sync-run  push + run + pull
"""
from __future__ import annotations

import argparse
import sys

from scripts.remote_backtesting_support import (
    RemoteBacktestingError,
    load_remote_config,
    pull_from_share,
    push_to_share,
    run_remote_backtesting,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remote-Backtesting über SMB-Share und SSH.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Pfad zu remote_backtesting.json (Standard: config/remote_backtesting.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("push", help="Lokale Daten auf den Share kopieren")
    sub.add_parser("pull", help="Ergebnisse vom Share ins lokale Repo holen")

    run_p = sub.add_parser("run", help="Backtesting auf dem Remote-PC starten")
    run_p.add_argument(
        "backtesting_args",
        nargs=argparse.REMAINDER,
        help="Argumente für scripts.run_backtesting (nach --)",
    )

    sync_p = sub.add_parser("sync-run", help="push, run und pull in einem Schritt")
    sync_p.add_argument(
        "backtesting_args",
        nargs=argparse.REMAINDER,
        help="Argumente für scripts.run_backtesting (nach --)",
    )
    return parser


def _normalize_backtesting_args(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    try:
        cfg_path = Path(ns.config) if ns.config else None
        cfg = load_remote_config(cfg_path)
    except RemoteBacktestingError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    bt_args = _normalize_backtesting_args(getattr(ns, "backtesting_args", []))

    try:
        if ns.command == "push":
            push_to_share(cfg)
        elif ns.command == "pull":
            pull_from_share(cfg)
        elif ns.command == "run":
            run_remote_backtesting(cfg, bt_args)
        elif ns.command == "sync-run":
            push_to_share(cfg)
            run_remote_backtesting(cfg, bt_args)
            pull_from_share(cfg)
        else:
            parser.error(f"Unbekannter Befehl: {ns.command}")
    except RemoteBacktestingError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
