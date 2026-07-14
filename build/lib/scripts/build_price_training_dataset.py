#!/usr/bin/env python3
"""Erzeugt das Preis-Training-Dataset (EU-Wetter + EU-Erzeugung + AT-Preise)."""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import requests

from data.eu_market_features import build_training_dataset, default_training_range


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    default_start, default_end = default_training_range()
    parser = argparse.ArgumentParser(
        description=(
            "Preis-Training-Dataset bauen (Spec: docs/spec/price-forecast-renewables.md). "
            "Lädt AT Day-Ahead, EU-Wind/Solar-Erzeugung und EU-Wetter."
        )
    )
    parser.add_argument(
        "--start",
        type=_parse_date,
        default=default_start,
        help=f"Startdatum inkl. (Standard: {default_start})",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        default=default_end,
        help=f"Enddatum exkl. (Standard: {default_end})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ziel-CSV (Standard: data/cache/price_training_<start>_<end>.csv)",
    )
    return parser.parse_args(argv)


def _default_output(start: date, end: date) -> Path:
    return Path("data/cache") / f"price_training_{start:%Y%m%d}_{end:%Y%m%d}.csv"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.end <= args.start:
        print("Fehler: --end muss nach --start liegen.", file=sys.stderr)
        return 1

    output = args.output or _default_output(args.start, args.end)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"Lade Training-Dataset {args.start} -> {args.end} "
        "(AT-Preise, EU-Erzeugung, EU-Wetter) ..."
    )
    try:
        dataset = build_training_dataset(args.start, args.end)
    except (OSError, ValueError, requests.HTTPError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    dataset.to_csv(output, index_label="slot_datetime")
    print(f"OK: {len(dataset)} Stunden geschrieben -> {output}")
    print("Spalten:", ", ".join(dataset.columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
