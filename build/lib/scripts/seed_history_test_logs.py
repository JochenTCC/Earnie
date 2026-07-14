#!/usr/bin/env python3
"""
Befüllt runtime/optimization_history.jsonl aus einem Prod-Dump für UI-Tests.

Verschiebt die Einträge auf aufeinanderfolgende 15-Min-Slots bis kurz vor den
aktuellen Live-Anker (Viertelstunde). Überschreibt die Zieldatei nur mit --force.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "runtime-prod" / "data" / "optimization_history.jsonl"
DEFAULT_TARGET = ROOT / "runtime" / "optimization_history.jsonl"


def _resolve_source(path: Path) -> Path:
    if path.is_file():
        return path
    for candidate in (
        path,
        path / "optimization_history.jsonl",
        path / "data" / "optimization_history.jsonl",
        path / "_full" / "optimization_history.jsonl",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Keine optimization_history.jsonl unter {path} "
        "(erwartet Datei oder Ordner mit data/ bzw. _full/)"
    )


def _entry_timestamp(entry: dict) -> datetime:
    for key in ("completed_at", "written_at"):
        raw = entry.get(key)
        if not raw:
            continue
        return datetime.fromisoformat(str(raw))
    raise ValueError("Eintrag ohne completed_at/written_at")


def _load_entries(path: Path) -> list[dict]:
    entries: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            if not isinstance(row, dict):
                raise ValueError(f"Zeile {line_no} in {path} ist kein JSON-Objekt")
            entries.append(row)
    if not entries:
        raise ValueError(f"{path} enthält keine Einträge")
    return sorted(entries, key=_entry_timestamp)


def _remap_entries(
    entries: list[dict],
    anchor: datetime,
) -> list[dict]:
    """Legt Einträge fortlaufend auf 15-Min-Slots bis anchor - 15 min."""
    end_slot = quarter_hour_slot_start(anchor) - timedelta(minutes=QUARTER_HOUR_MINUTES)
    start_slot = end_slot - timedelta(minutes=QUARTER_HOUR_MINUTES * (len(entries) - 1))
    remapped: list[dict] = []
    for index, entry in enumerate(entries):
        slot = start_slot + timedelta(minutes=QUARTER_HOUR_MINUTES * index)
        slot_text = slot.isoformat(timespec="seconds")
        row = dict(entry)
        row["completed_at"] = slot_text
        row["written_at"] = slot_text
        row["source"] = "seed_history_test_logs.py"
        remapped.append(row)
    return remapped


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False))
            handle.write("\n")


def seed_history_logs(
    source: Path,
    target: Path,
    *,
    anchor: datetime | None = None,
    max_entries: int | None = None,
) -> dict:
    source_path = _resolve_source(source)
    entries = _load_entries(source_path)
    if max_entries is not None and max_entries > 0:
        entries = entries[-max_entries:]
    anchor_slot = quarter_hour_slot_start(anchor)
    remapped = _remap_entries(entries, anchor_slot)
    _write_jsonl(target, remapped)
    first_slot = _entry_timestamp(remapped[0])
    last_slot = _entry_timestamp(remapped[-1])
    span_hours = (last_slot - first_slot).total_seconds() / 3600.0 + 0.25
    return {
        "source": str(source_path),
        "target": str(target),
        "entries": len(remapped),
        "first_slot": first_slot.isoformat(timespec="seconds"),
        "last_slot": last_slot.isoformat(timespec="seconds"),
        "anchor": anchor_slot.isoformat(timespec="seconds"),
        "span_hours": round(span_hours, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Prod-Dump (Datei oder Ordner mit optimization_history.jsonl)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Ziel-jsonl (Standard: runtime/optimization_history.jsonl)",
    )
    parser.add_argument(
        "--max-entries",
        type=int,
        default=None,
        help="Nur die letzten N Einträge übernehmen (Standard: alle)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bestehende Zieldatei überschreiben",
    )
    args = parser.parse_args()

    if args.target.is_file() and not args.force:
        raise SystemExit(
            f"Zieldatei existiert bereits: {args.target}\n"
            "Zum Überschreiben --force angeben."
        )
    if args.target.is_file() and args.force:
        backup = args.target.with_suffix(".jsonl.bak")
        shutil.copy2(args.target, backup)
        print(f"Backup: {backup}")

    summary = seed_history_logs(
        args.source,
        args.target,
        max_entries=args.max_entries,
    )
    print(
        f"{summary['entries']} Eintraege nach {summary['target']} geschrieben\n"
        f"Slots: {summary['first_slot']} -> {summary['last_slot']} "
        f"({summary['span_hours']} h, Anker {summary['anchor']})"
    )


if __name__ == "__main__":
    main()
