#!/usr/bin/env python3
"""Ergänzt bestehende Training-CSVs um EU-Last und Residuallast."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data.eu_market_features import enrich_dataset_with_eu_load
from data.price_forecast_model import load_training_dataset


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="eu_load_mw und eu_residual_load_mw zu price_training_*.csv hinzufügen"
    )
    parser.add_argument("dataset", type=Path, help="Pfad zur CSV in data/cache/")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ziel-CSV (Standard: überschreibt Eingabedatei)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output = args.output or args.dataset
    try:
        frame = load_training_dataset(
            args.dataset,
            feature_variant="base",
        )
        enriched = enrich_dataset_with_eu_load(frame)
    except (OSError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    enriched.to_csv(output, index_label="slot_datetime")
    print(f"OK: {len(enriched)} Stunden -> {output}")
    print("Neue Spalten: eu_load_mw, eu_residual_load_mw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
