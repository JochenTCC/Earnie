#!/usr/bin/env python3
"""Aggregate raw GitHub traffic snapshots into a public summary.json.

Reads all traffic/<repo>-<clones|views>-<timestamp>.json snapshots (as
produced by the GitHub traffic API, each covering a rolling 14-day window),
deduplicates per repo/day (most recent snapshot wins for a given day), and
writes a summary containing only aggregate daily totals - no referrers, no
paths, no raw payloads.

Usage: aggregate_stats.py <traffic_dir> <output_summary.json>
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_RE = re.compile(r"^(?P<repo>.+)-(?P<metric>clones|views)-(?P<ts>\d{8}T\d{4})\.json$")


def parse_snapshot_filename(name: str) -> tuple[str, str, str] | None:
    match = SNAPSHOT_RE.match(name)
    if not match:
        return None
    return match.group("repo"), match.group("metric"), match.group("ts")


def load_json(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        return json.loads(text)
    except (json.JSONDecodeError, OSError):
        return {}


def collect_snapshots(traffic_dir: Path) -> dict[str, dict[str, list[tuple[str, dict]]]]:
    """Returns {repo: {metric: [(snapshot_ts, payload), ...]}}"""
    by_repo: dict[str, dict[str, list[tuple[str, dict]]]] = {}
    for path in sorted(traffic_dir.glob("*.json")):
        parsed = parse_snapshot_filename(path.name)
        if not parsed:
            continue
        repo, metric, ts = parsed
        payload = load_json(path)
        by_repo.setdefault(repo, {}).setdefault(metric, []).append((ts, payload))
    return by_repo


def dedupe_daily(snapshots: list[tuple[str, dict]]) -> dict[str, dict]:
    """Flattens overlapping 14-day-window snapshots into per-day values.

    GitHub's traffic API returns entries like:
      {"clones": [{"timestamp": "2026-09-01T00:00:00Z", "count": 5, "uniques": 3}, ...]}
    or the analogous "views" key. Snapshots taken later carry more complete/
    recent data for a given day, so later snapshot_ts wins on conflict.
    """
    daily: dict[str, dict] = {}
    for snapshot_ts, payload in sorted(snapshots, key=lambda item: item[0]):
        entries = payload.get("clones") or payload.get("views") or []
        for entry in entries:
            ts = entry.get("timestamp")
            if not ts:
                continue
            date = ts[:10]
            daily[date] = {
                "count": entry.get("count", 0),
                "uniques": entry.get("uniques", 0),
            }
    return daily


def build_summary(traffic_dir: Path) -> dict:
    by_repo = collect_snapshots(traffic_dir)
    repos_out: dict[str, dict] = {}

    for repo in sorted(by_repo):
        clones_daily = dedupe_daily(by_repo[repo].get("clones", []))
        views_daily = dedupe_daily(by_repo[repo].get("views", []))

        all_dates = sorted(set(clones_daily) | set(views_daily))
        daily_out = []
        for date in all_dates:
            c = clones_daily.get(date, {"count": 0, "uniques": 0})
            v = views_daily.get(date, {"count": 0, "uniques": 0})
            daily_out.append(
                {
                    "date": date,
                    "clones_total": c["count"],
                    "clones_unique": c["uniques"],
                    "views_total": v["count"],
                    "views_unique": v["uniques"],
                }
            )

        repos_out[repo] = {
            "daily": daily_out,
            "since": all_dates[0] if all_dates else None,
        }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repos": repos_out,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <traffic_dir> <output_summary.json>", file=sys.stderr)
        return 1

    traffic_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not traffic_dir.is_dir():
        summary = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "repos": {}}
    else:
        summary = build_summary(traffic_dir)

    output_path.write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"Wrote {output_path} with {len(summary['repos'])} repo(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
