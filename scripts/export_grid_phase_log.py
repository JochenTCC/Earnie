"""Export grid per-phase pushes from the Shadow feed into the device-detection log format.

A Shadow client has no live push listener, so ``runtime_store.grid_phase_log`` never
writes there. The Prod feed recorder already keeps every Loxone VO push
(``feed-YYYY-MM-DD.jsonl``, key ``loxone:io:<ehal_id>``); this script turns the
``grid.meter.*`` rows of those files into ``grid_phase_log/YYYY-MM-DD.jsonl``:

    {"ts": "2026-10-29T11:00:02+00:00", "id": "grid.meter.sens_grid_voltage_l1", "v": 233.0}

Differences to the live log (see ``docs/dev/nilm-grid-phase-logging.md``):

* ``ts`` has second resolution (feed timestamp), not milliseconds.
* Once per cycle the Prod recorder mirrors the whole push inbox into the feed. Those
  snapshot rows repeat the last pushed value shortly after the real push. A row is
  dropped as snapshot when it has the same raw value as the previous row of that ID and
  follows it by less than half of the ID's median push interval. ``--keep-snapshots``
  keeps every row. The number of dropped rows is printed per day.

Usage::

    python -m scripts.export_grid_phase_log --feed-dir <prod config>/shadow_feed \\
        --out-dir <runtime>/grid_phase_log [--from 2026-10-29] [--to 2026-10-30] [--overwrite]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ehal.grid_phase_fields import grid_phase_log_ids
from runtime_store.loxone_push_parse import parse_push_value

FEED_KEY_PREFIX = "loxone:io:"
FEED_GLOB = "feed-*.jsonl"

_LOG_IDS = grid_phase_log_ids()


@dataclass(frozen=True)
class FeedPush:
    ts: datetime
    ehal_id: str
    raw: str


@dataclass(frozen=True)
class DayExport:
    day: str
    path: Path
    written: int
    snapshots_dropped: int


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def read_feed_pushes(path: Path) -> list[FeedPush]:
    """Grid meter push rows of one feed file, in file (arrival) order."""
    pushes: list[FeedPush] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if FEED_KEY_PREFIX + "grid.meter." not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON ({exc})") from exc
            key = str(row.get("key") or "")
            ehal_id = key[len(FEED_KEY_PREFIX):] if key.startswith(FEED_KEY_PREFIX) else ""
            if ehal_id not in _LOG_IDS:
                continue
            payload = row.get("payload") or {}
            raw = str((payload.get("LL") or {}).get("value") or "")
            pushes.append(FeedPush(ts=_parse_ts(str(row["ts"])), ehal_id=ehal_id, raw=raw))
    return pushes


def _median_intervals(pushes: list[FeedPush]) -> dict[str, float]:
    last: dict[str, datetime] = {}
    deltas: dict[str, list[float]] = {}
    for push in pushes:
        previous = last.get(push.ehal_id)
        if previous is not None:
            delta = (push.ts - previous).total_seconds()
            if delta > 0:
                deltas.setdefault(push.ehal_id, []).append(delta)
        last[push.ehal_id] = push.ts
    return {ehal_id: statistics.median(values) for ehal_id, values in deltas.items()}


def drop_cycle_snapshots(pushes: list[FeedPush]) -> tuple[list[FeedPush], int]:
    """Remove inbox-snapshot rows (same raw, closer than half the median interval)."""
    medians = _median_intervals(pushes)
    kept: list[FeedPush] = []
    previous: dict[str, FeedPush] = {}
    dropped = 0
    for push in pushes:
        before = previous.get(push.ehal_id)
        median = medians.get(push.ehal_id)
        if (
            before is not None
            and median is not None
            and push.raw == before.raw
            and (push.ts - before.ts).total_seconds() < median / 2
        ):
            dropped += 1
            continue
        kept.append(push)
        previous[push.ehal_id] = push
    return kept, dropped


def log_line(push: FeedPush) -> str:
    value = parse_push_value(push.raw)
    row: dict[str, object] = {"ts": push.ts.isoformat(), "id": push.ehal_id, "v": value}
    if value is None:
        row["raw"] = push.raw
    return json.dumps(row, separators=(",", ":")) + "\n"


def _feed_day(path: Path) -> str:
    return path.stem[len("feed-"):]


def feed_files(feed_dir: Path, *, day_from: date | None, day_to: date | None) -> list[Path]:
    """Feed files in *feed_dir* whose day lies in [day_from, day_to] (inclusive)."""
    selected: list[Path] = []
    for path in sorted(feed_dir.glob(FEED_GLOB)):
        day = date.fromisoformat(_feed_day(path))
        if day_from is not None and day < day_from:
            continue
        if day_to is not None and day > day_to:
            continue
        selected.append(path)
    return selected


def export_day(
    feed_file: Path, out_dir: Path, *, overwrite: bool, keep_snapshots: bool
) -> DayExport:
    """Write ``<out_dir>/<day>.jsonl`` from one feed file. Refuses to replace unless *overwrite*."""
    day = _feed_day(feed_file)
    target = out_dir / f"{day}.jsonl"
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} exists (use --overwrite to replace it)")
    pushes = read_feed_pushes(feed_file)
    dropped = 0
    if not keep_snapshots:
        pushes, dropped = drop_cycle_snapshots(pushes)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for push in pushes:
            handle.write(log_line(push))
    tmp.replace(target)
    return DayExport(day=day, path=target, written=len(pushes), snapshots_dropped=dropped)


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--feed-dir", required=True, type=Path, help="Prod shadow_feed directory")
    parser.add_argument("--out-dir", required=True, type=Path, help="target grid_phase_log directory")
    parser.add_argument("--from", dest="day_from", type=date.fromisoformat, help="first feed day (UTC, YYYY-MM-DD)")
    parser.add_argument("--to", dest="day_to", type=date.fromisoformat, help="last feed day (UTC, YYYY-MM-DD)")
    parser.add_argument("--overwrite", action="store_true", help="replace existing day files")
    parser.add_argument("--keep-snapshots", action="store_true", help="keep per-cycle inbox snapshot rows")
    args = parser.parse_args(argv)

    if not args.feed_dir.is_dir():
        print(f"feed directory not found: {args.feed_dir}", file=sys.stderr)
        return 2
    files = feed_files(args.feed_dir, day_from=args.day_from, day_to=args.day_to)
    if not files:
        print(f"no {FEED_GLOB} in {args.feed_dir} for the given range", file=sys.stderr)
        return 2
    try:
        for feed_file in files:
            result = export_day(
                feed_file, args.out_dir, overwrite=args.overwrite, keep_snapshots=args.keep_snapshots
            )
            print(
                f"{result.day}: {result.written} pushes -> {result.path}"
                f" (snapshot rows dropped: {result.snapshots_dropped})"
            )
    except (FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
