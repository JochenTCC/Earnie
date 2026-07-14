#!/usr/bin/env python3
"""Extrahiert tests/fixtures/backtesting/cons_data_hourly.csv aus runtime/cons_data_hourly.csv."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "runtime" / "cons_data_hourly.csv"
DEFAULT_TARGET = REPO_ROOT / "tests" / "fixtures" / "backtesting" / "cons_data_hourly.csv"

RANGES: list[tuple[str, str]] = [
    ("2024-07-02", "2024-07-05 23:00:00"),
    ("2026-06-22 00:00:00", "2026-06-26 23:00:00"),
]


def extract(source: Path, target: Path) -> int:
    if not source.is_file():
        raise FileNotFoundError(
            f"Quelldatei fehlt: {source}. "
            "Bitte runtime/cons_data_hourly.csv bereitstellen."
        )
    df = pd.read_csv(source, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    parts: list[pd.DataFrame] = []
    for start_s, end_s in RANGES:
        start = pd.Timestamp(start_s)
        end = pd.Timestamp(end_s)
        parts.append(df[(df["timestamp"] >= start) & (df["timestamp"] <= end)])
    sub = pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp")
    target.parent.mkdir(parents=True, exist_ok=True)
    sub.to_csv(target, sep=";", index=False)
    return len(sub)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    rows = extract(args.source, args.target)
    print(f"{rows} Zeilen nach {args.target} geschrieben.")


if __name__ == "__main__":
    main()
