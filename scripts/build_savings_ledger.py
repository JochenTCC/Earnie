#!/usr/bin/env python3
"""CLI: build the savings ledger from the production log (Ledger P6).

Replays ``optimization_history.jsonl`` and its rotated month files through the
ledger engine (spec ``docs/dev/savings-ledger.md`` § 4) and prints one line per
SA-day. Writes ``savings_ledger.jsonl``, ``savings_ledger_slots.jsonl`` and
``savings_ledger_state.json`` next to the log; an existing ledger is only replaced
with ``--rebuild`` (never merged with live rows). The daemon must be stopped while
it writes: it keeps the state in memory and would overwrite the rebuilt one.

``--slots-only`` leaves the ledger and the state alone and only writes the slot
file, after checking that the replay adds up to every existing ledger row and has
no other closed day. ``--since`` must then be the date the chain was built from.

    python -m scripts.build_savings_ledger --since 2026-07-01 --dry-run
    python -m scripts.build_savings_ledger --since 2026-07-01 --rebuild
    python -m scripts.build_savings_ledger --since 2026-07-01 --slots-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from optimizer.schedule import quarter_hour_slot_start  # noqa: E402
from runtime_store import savings_ledger as sl  # noqa: E402
from runtime_store import savings_ledger_store as store  # noqa: E402
from runtime_store.history_chart_rows import _parse_completed_at  # noqa: E402
from runtime_store.month_file_rotation import list_rotated_siblings  # noqa: E402
from runtime_store.optimization_history import HISTORY_FILENAME  # noqa: E402
from version import __version__  # noqa: E402

LEDGER_FILENAME = "savings_ledger.jsonl"
SLOTS_FILENAME = "savings_ledger_slots.jsonl"
STATE_FILENAME = "savings_ledger_state.json"

# Log fields the ledger reads; everything else is dropped while streaming (a
# month file is ~100 MB, the slim entries of a year fit in memory).
_KEPT_FIELDS = (
    "completed_at",
    "written_at",
    "closed_interval",
    "market_price_cent",
    "epex_price_cent",
    "k_push_act",
)


def history_files(runtime_dir: str) -> list[str]:
    """Rotated month files (oldest first), then the active file."""
    active = os.path.join(runtime_dir, HISTORY_FILENAME)
    paths = list_rotated_siblings(active)
    if os.path.isfile(active):
        paths.append(active)
    return paths


def _slim(entry: dict[str, Any]) -> dict[str, Any]:
    slim = {key: entry[key] for key in _KEPT_FIELDS if key in entry}
    planned = {
        cid: {"planned_kw": item["planned_kw"]}
        for cid, item in (entry.get("delivery_compliance") or {}).items()
        if isinstance(item, dict) and item.get("planned_kw") is not None
    }
    if planned:
        slim["delivery_compliance"] = planned
    return slim


def read_entries(
    paths: list[str],
    not_before: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Slim log entries completed at or after ``not_before``; malformed lines are reported."""
    entries: list[dict[str, Any]] = []
    bad: list[str] = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    bad.append(f"{path}:{number}: {exc}")
                    continue
                if not isinstance(entry, dict):
                    bad.append(f"{path}:{number}: not an object")
                    continue
                completed = _parse_completed_at(entry)
                if completed is None or completed < not_before:
                    continue
                entries.append(_slim(entry))
    return entries, bad


def build(
    entries: list[dict[str, Any]],
    since: datetime,
    battery: dict[str, Any],
    day_bounds: sl.DayBounds,
    timezone_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], sl.LedgerState | None, int]:
    """Run the engine over every closed slot from ``since`` as one chain (``backfill``).

    Returns the closed-day rows, their slot records, the state with the open day
    (``None`` without any slot that has a SoC) and the number of closed slots read.
    """
    inputs = [
        inp
        for inp in store.ledger_inputs_from_entries(entries, timezone_name)
        if inp.slot_start >= since
    ]
    state: sl.LedgerState | None = None
    rows: list[dict[str, Any]] = []
    slot_records: list[dict[str, Any]] = []
    # Same day close as the daemon: a v2 chain replays each day with the current configuration.
    day_flex = store.flex_day_provider(timezone_name)
    for inp in inputs:
        if state is None:
            state = sl.start_chain(inp, day_bounds, reason=sl.CHAIN_BACKFILL)
            if state is None:
                continue
        state, closed_day = sl.advance_with_slots(
            state, inp, battery, day_bounds, app_version=__version__, day_flex=day_flex
        )
        if closed_day is not None:
            rows.append(closed_day.row)
            slot_records.append(sl.day_slots_record(closed_day.closing))
    if state is not None and entries:
        # The newest entry's own slot is not closed yet: keep its prices for the
        # daemon, as its hook does after every cycle.
        last = max(entries, key=_parse_completed_at)
        slot = quarter_hour_slot_start(_parse_completed_at(last))
        state = replace(state, pending_slot=store.pending_slot_from_entry(slot, last))
    return rows, slot_records, state, len(inputs)


def _write_rows(path: str, rows: list[dict[str, Any]]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def check_slots_against_ledger(
    ledger_rows: list[dict[str, Any]],
    slot_records: list[dict[str, Any]],
) -> None:
    """Raise ``SlotFileError`` unless the replayed days are exactly the ledger's days and add up to them."""
    records = {record["day_start"]: record for record in slot_records}
    store.check_rows_against_slots(ledger_rows, records)
    extra = sorted(set(records) - {row["day_start"] for row in ledger_rows})
    if extra:
        raise store.SlotFileError(
            f"the replay closes {len(extra)} day(s) the ledger does not have, first {extra[0]}; "
            "check --since"
        )


def format_table(rows: list[dict[str, Any]]) -> list[str]:
    """One line per SA-day: cost with / without, saving, the day's correction, adjusted saving."""
    lines = ["SA-day      coverage  with €  without €  saving €  corr €  adjusted €"]
    for r in rows:
        flag = "  incomplete" if r["incomplete"] else ""
        lines.append(
            f"{r['day_start'][:10]}  {r['coverage']:8.2f}  {r['cost_with_eur']:6.2f}  "
            f"{r['cost_without_eur']:9.2f}  {r['saving_eur']:8.2f}  "
            f"{r['soc_correction_eur'] - r['soc_correction_prev_eur']:6.2f}  "
            f"{r['saving_adjusted_eur']:10.2f}{flag}"
        )
    return lines


def _daemon_running(runtime_dir: str) -> bool:
    """True when the daemon of this machine's runtime folder holds its lock."""
    from runtime_store import main_daemon
    from runtime_store.persist_paths_base import runtime_dir as default_runtime_dir

    if os.path.abspath(runtime_dir) != os.path.abspath(default_runtime_dir()):
        return False
    return main_daemon.status().state == "running"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the savings ledger from the production log.")
    parser.add_argument(
        "--since",
        required=True,
        type=date.fromisoformat,
        help="first local date to replay (YYYY-MM-DD); the chain starts at its first slot with a SoC",
    )
    parser.add_argument(
        "--runtime-dir",
        help="folder with optimization_history.jsonl* (default: the configured runtime folder)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rebuild", action="store_true", help="replace an existing ledger")
    mode.add_argument("--dry-run", action="store_true", help="print the table, write nothing")
    parser.add_argument(
        "--slots-only",
        action="store_true",
        help="write only the slot file; refuses unless the replay matches every existing ledger row",
    )
    args = parser.parse_args(argv)
    if args.slots_only and args.rebuild:
        parser.error("--slots-only keeps the ledger; it cannot be combined with --rebuild")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from runtime_store.persist_paths_base import runtime_dir as default_runtime_dir

    runtime_dir = args.runtime_dir or default_runtime_dir()
    ledger_path = os.path.join(runtime_dir, LEDGER_FILENAME)
    slots_path = os.path.join(runtime_dir, SLOTS_FILENAME)
    state_path = os.path.join(runtime_dir, STATE_FILENAME)
    existing = [p for p in (ledger_path, slots_path, state_path) if os.path.exists(p)]
    if not args.dry_run:
        if existing and not args.rebuild and not args.slots_only:
            print(
                "Ledger exists, nothing written (--rebuild replaces it, --dry-run only prints):",
                file=sys.stderr,
            )
            for path in existing:
                print(f"  {path}", file=sys.stderr)
            return 2
        if _daemon_running(runtime_dir):
            print("The Earnie daemon is running; stop it before writing the ledger.", file=sys.stderr)
            return 2

    batteries = config.get_battery_params_list()
    if not batteries:
        print("No house battery configured: the ledger has nothing to book.", file=sys.stderr)
        return 1
    battery = sl.shadow_battery_params(batteries)
    timezone_name = config.get_planning_timezone()
    since = datetime.combine(args.since, datetime.min.time(), tzinfo=ZoneInfo(timezone_name))
    day_bounds = store.sunrise_day_bounds(
        config.get("LATITUDE", cast=float),
        config.get("LONGITUDE", cast=float),
        timezone_name,
    )

    paths = history_files(runtime_dir)
    if not paths:
        print(f"No {HISTORY_FILENAME} in {runtime_dir}.", file=sys.stderr)
        return 1
    # The prices of the first slot come from the entry written in it.
    entries, bad = read_entries(paths, since - timedelta(minutes=15))
    rows, slot_records, state, slots_read = build(entries, since, battery, day_bounds, timezone_name)

    for line in bad:
        print(f"skipped malformed log line {line}", file=sys.stderr)
    print(
        f"{len(paths)} log file(s), {slots_read} closed slots since {args.since}, "
        f"{len(bad)} malformed line(s)"
    )
    if state is None:
        print("No slot with a SoC since that date: no chain, nothing written.", file=sys.stderr)
        return 1
    print(
        f"chain {state.chain_start:%Y-%m-%d %H:%M} ({state.chain_start_reason}), "
        f"battery {battery['battery_capacity_kwh']} kWh, path efficiency {battery['efficiency']:.3f}, "
        f"standby {battery.get('standby_power_kw', 0.0)} kW"
    )
    for line in format_table(rows):
        print(line)
    total = sl.lifetime_summary(rows, state.chain_start)
    print(
        f"total {total['saving_adjusted_eur']:.2f} EUR over {total['days']} closed SA-days "
        f"({total['incomplete_days']} incomplete); the open day from "
        f"{state.day_start:%Y-%m-%d %H:%M} stays in the state"
    )
    if args.slots_only:
        try:
            ledger_rows = store.read_rows(ledger_path)
            if not ledger_rows:
                raise store.SlotFileError(f"no ledger rows in {ledger_path}; nothing to match")
            check_slots_against_ledger(ledger_rows, slot_records)
        except ValueError as exc:
            print(f"Slot file not written: {exc}", file=sys.stderr)
            return 1
        print(f"replay matches all {len(ledger_rows)} ledger rows")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    os.makedirs(runtime_dir, exist_ok=True)
    _write_rows(slots_path, slot_records)
    if args.slots_only:
        print(f"written: {slots_path} ({len(slot_records)} days); ledger and state unchanged")
        return 0
    _write_rows(ledger_path, rows)
    store.save_state(state, state_path)
    print(f"written: {ledger_path} ({len(rows)} rows), {slots_path}, {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
