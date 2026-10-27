"""Fetch day-ahead prices once (online) and freeze them as a CSV for offline runs.

Writes the Energy-Charts CSV layout that ``data.data_loader._prepare_energy_charts_prices``
reads (``price_source: csv``). The price column is named after the zone passed via
``--zone`` (default AT), e.g. ``Day Ahead Auktion (AT)``; the loader picks the column
of the scenario's market zone.

  python -m studies.poc_cloud.fetch_prices --start 2025-01-01 --end 2026-01-04
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from data.data_loader import energy_charts_price_column

STUDY_DIR = Path(__file__).resolve().parent
CACHE_DIR = STUDY_DIR / "cache"
URL = "https://api.energy-charts.info/price"
HEADERS = {"User-Agent": "Earnie-SE/2.5 (study cache)", "Accept": "application/json"}


def _month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        nxt = min((cur.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1), end)
        chunks.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return chunks


def fetch(zone: str, start: date, end: date) -> pd.DataFrame:
    frames = []
    for chunk_start, chunk_end in _month_chunks(start, end):
        params = {"bzn": zone, "start": chunk_start.isoformat(), "end": chunk_end.isoformat()}
        for attempt in range(6):
            response = requests.get(URL, params=params, headers=HEADERS, timeout=60)
            if response.status_code != 429:
                break
            time.sleep(float(response.headers.get("Retry-After", 5 * (attempt + 1))))
        response.raise_for_status()
        payload = response.json()
        time.sleep(1.0)
        if not payload.get("unix_seconds"):
            raise SystemExit(f"Energy-Charts: no prices for {zone} {chunk_start}..{chunk_end}")
        frames.append(
            pd.DataFrame(
                {
                    "ts": pd.to_datetime(payload["unix_seconds"], unit="s", utc=True),
                    "eur_mwh": pd.to_numeric(payload["price"], errors="coerce"),
                }
            )
        )
    frame = pd.concat(frames).dropna().drop_duplicates("ts").sort_values("ts")
    return frame.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", default="AT")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, default=CACHE_DIR / "prices_AT_2025.csv")
    args = parser.parse_args()

    frame = fetch(args.zone, args.start, args.end)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        handle.write(f"Datum (MEZ),{LOADER_PRICE_COLUMN}\n")
        handle.write("Datum,EUR/MWh\n")  # units row, skipped by the loader (skiprows=[1])
        for ts, price in zip(frame["ts"], frame["eur_mwh"]):
            handle.write(f"{ts.isoformat()},{price}\n")
    manifest = {
        "source": URL,
        "zone": args.zone,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "rows": int(len(frame)),
        "first_ts": frame["ts"].iloc[0].isoformat(),
        "last_ts": frame["ts"].iloc[-1].isoformat(),
        "fetched_on": date.today().isoformat(),
    }
    args.out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
