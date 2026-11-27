#!/usr/bin/env python3
"""Builds the EU power country shares the live price forecast uses to stand in a country.

Energy-Charts sometimes publishes no ``public_power`` data for a country (Denmark since
2026-11-04). The live forecast then scales the sum of the other countries by that
country's share (``data.eu_market_features.fetch_eu_power_hourly_with_stand_in``). This
script computes the shares per country, column, month and hour from one year of archive
data, with every country present, and writes ``share/data/eu_power_country_shares.json``.

    python -m scripts.build_eu_power_country_shares --start 2024-11-01 --end 2025-11-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from data.eu_market_features import (
    DEFAULT_COUNTRY_SHARES_PATH,
    compute_country_shares,
    fetch_country_power_frames,
    save_country_shares,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="first day (inclusive)")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="last day (exclusive)")
    parser.add_argument("--output", type=Path, default=DEFAULT_COUNTRY_SHARES_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    frames, _missing = fetch_country_power_frames(args.start, args.end)
    shares = compute_country_shares(frames, range_start=args.start, range_end=args.end)
    save_country_shares(shares, args.output)
    print(f"Länderanteile {args.start} bis {args.end} -> {args.output}")
    for base in ("wind_mw", "solar_mw", "load_mw", "residual_load_mw"):
        means = {
            country: sum(sum(row) for row in table[base]) / (12 * 24)
            for country, table in shares.shares.items()
        }
        top = ", ".join(f"{c}={v:.1%}" for c, v in sorted(means.items(), key=lambda kv: -kv[1]))
        print(f"  {base}: {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
