#!/usr/bin/env python3
"""Build a CSV report from the public repo-stats summary.json.

Fetches (or reads locally) the aggregated traffic summary published to
JochenTCC/repo-stats-public and writes a CSV report for offline/own use
(no website involved): a per-repo summary section (totals, last-7-days
vs previous-7-days trend) followed by the full daily detail table.

Usage:
    scripts/report_repo_stats.py [-o report.csv]
    scripts/report_repo_stats.py --input path/to/summary.json [-o report.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from datetime import date, timedelta
from io import StringIO

DEFAULT_URL = "https://raw.githubusercontent.com/JochenTCC/repo-stats-public/main/stats/summary.json"


def load_summary(url: str | None, input_path: str | None) -> dict:
    if input_path:
        with open(input_path, encoding="utf-8") as f:
            return json.load(f)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.load(resp)


def sum_window(daily: list[dict], field: str, start: date, end: date) -> int:
    total = 0
    for entry in daily:
        try:
            d = date.fromisoformat(entry["date"])
        except (KeyError, ValueError):
            continue
        if start <= d <= end:
            total += entry.get(field, 0)
    return total


def build_summary_rows(repos: dict) -> list[list]:
    today = date.today()
    last7_start, last7_end = today - timedelta(days=7), today - timedelta(days=1)
    prev7_start, prev7_end = today - timedelta(days=14), today - timedelta(days=8)

    rows = [["repo", "clones_total", "clones_unique", "views_total", "views_unique",
             "clones_last7", "clones_prev7", "clones_trend_pct",
             "views_last7", "views_prev7", "views_trend_pct", "since"]]

    for repo, info in sorted(repos.items()):
        daily = info.get("daily", [])
        clones_total = sum(d.get("clones_total", 0) for d in daily)
        clones_unique = sum(d.get("clones_unique", 0) for d in daily)
        views_total = sum(d.get("views_total", 0) for d in daily)
        views_unique = sum(d.get("views_unique", 0) for d in daily)

        clones_last7 = sum_window(daily, "clones_total", last7_start, last7_end)
        clones_prev7 = sum_window(daily, "clones_total", prev7_start, prev7_end)
        views_last7 = sum_window(daily, "views_total", last7_start, last7_end)
        views_prev7 = sum_window(daily, "views_total", prev7_start, prev7_end)

        def trend_pct(curr: int, prev: int) -> str:
            if prev == 0:
                return "n/a" if curr == 0 else "+inf"
            return f"{(curr - prev) / prev * 100:+.1f}"

        rows.append([
            repo, clones_total, clones_unique, views_total, views_unique,
            clones_last7, clones_prev7, trend_pct(clones_last7, clones_prev7),
            views_last7, views_prev7, trend_pct(views_last7, views_prev7),
            info.get("since", ""),
        ])
    return rows


def build_daily_rows(repos: dict) -> list[list]:
    rows = [["repo", "date", "clones_total", "clones_unique", "views_total", "views_unique"]]
    for repo, info in sorted(repos.items()):
        for entry in sorted(info.get("daily", []), key=lambda d: d.get("date", "")):
            rows.append([
                repo, entry.get("date", ""),
                entry.get("clones_total", 0), entry.get("clones_unique", 0),
                entry.get("views_total", 0), entry.get("views_unique", 0),
            ])
    return rows


def render_csv(summary: dict) -> str:
    repos = summary.get("repos", {})
    buf = StringIO()
    writer = csv.writer(buf)

    writer.writerow([f"# Repo-Stats Report - generated_at (Quelle): {summary.get('generated_at', 'unbekannt')}"])
    writer.writerow([])
    writer.writerow(["## Zusammenfassung (Summen gesamt, 7-Tage-Trend)"])
    writer.writerows(build_summary_rows(repos))
    writer.writerow([])
    writer.writerow(["## Tagesdetails"])
    writer.writerows(build_daily_rows(repos))

    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="Lokale summary.json statt Live-Abruf verwenden")
    parser.add_argument("--url", default=DEFAULT_URL, help="Quelle fuer summary.json (default: %(default)s)")
    parser.add_argument("-o", "--output", help="Zieldatei (default: stdout)")
    args = parser.parse_args()

    summary = load_summary(None if args.input else args.url, args.input)
    csv_text = render_csv(summary)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        print(f"Report geschrieben: {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(csv_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
