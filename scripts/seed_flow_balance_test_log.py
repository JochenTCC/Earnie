#!/usr/bin/env python3
"""
Erzeugt ein fiktives Produktiv-Log zum Testen der Chart-1-Rauf/Runter-Balken.

Acht Energiebilanz-Szenarien (A–H) aus ``scripts.flow_balance_test_data`` werden auf
aufeinanderfolgende 15-Min-Slots bis kurz vor den Live-Anker gelegt.

Aufruf:
    python -m scripts.seed_flow_balance_test_log --force

VS Code: Launch **Streamlit app.py (Flow-Balance-Test)**.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

from optimizer.schedule import quarter_hour_slot_start
from runtime_store.history_timeline import entry_to_chart_row
from scripts.flow_balance_test_data import (
    build_flow_balance_history_entries,
    flow_balance_flex_pairs,
    flow_balance_scenario_rows,
    validate_flow_balance_scenarios,
)
from scripts.seed_history_test_logs import _remap_entries, _write_jsonl
from ui.chart_flow_balance import build_flow_balance_segments

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "runtime" / "optimization_history.jsonl"


def seed_flow_balance_test_log(
    target: Path,
    *,
    anchor: datetime | None = None,
) -> dict:
    validate_flow_balance_scenarios()
    entries = build_flow_balance_history_entries()
    anchor_slot = quarter_hour_slot_start(anchor)
    remapped = _remap_entries(entries, anchor_slot)
    for row in remapped:
        row["source"] = "seed_flow_balance_test_log.py"
    _validate_history_chart_rows(remapped)
    _write_jsonl(target, remapped)
    scenario_slots = [
        {
            "scenario_id": row.get("scenario", "").replace("flow_balance_", ""),
            "title": row.get("scenario_title", ""),
            "slot": row["completed_at"],
        }
        for row in remapped
    ]
    return {
        "target": str(target),
        "entries": len(remapped),
        "first_slot": remapped[0]["completed_at"],
        "last_slot": remapped[-1]["completed_at"],
        "anchor": anchor_slot.isoformat(timespec="seconds"),
        "scenario_slots": scenario_slots,
    }


def _validate_history_chart_rows(entries: list[dict]) -> None:
    """Chart-Zeilen aus dem Log müssen zu den Szenario-Metadaten passen."""
    flex = flow_balance_flex_pairs()
    scenarios = {item.scenario_id: item for item in flow_balance_scenario_rows()}
    for entry in entries:
        scenario_id = str(entry.get("scenario", "")).replace("flow_balance_", "")
        meta = scenarios[scenario_id]
        slot_start = datetime.fromisoformat(entry["completed_at"])
        chart_row = entry_to_chart_row(entry, slot_start)
        slot = build_flow_balance_segments(chart_row, flex_consumers=flex)
        if slot.offset_kw != meta.offset_kw:
            raise ValueError(
                f"Log-Szenario {scenario_id}: Chart-offset {slot.offset_kw} "
                f"!= {meta.offset_kw}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Ziel-jsonl (Standard: runtime/optimization_history.jsonl)",
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

    summary = seed_flow_balance_test_log(args.target)
    print(
        f"{summary['entries']} Eintraege nach {summary['target']} geschrieben\n"
        f"Slots: {summary['first_slot']} -> {summary['last_slot']} "
        f"(Anker {summary['anchor']})"
    )
    print("\nSzenario-Slots:")
    for item in summary["scenario_slots"]:
        print(f"  {item['slot']}  {item['scenario_id']}: {item['title']}")


if __name__ == "__main__":
    main()
