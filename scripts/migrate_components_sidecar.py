#!/usr/bin/env python3
"""Extrahiert batteries[] und pv_systems[] aus config.json nach components.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def migrate_config_dir(config_dir: Path, *, dry_run: bool = False) -> list[str]:
    config_path = config_dir / "config.json"
    components_path = config_dir / "components.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"config.json nicht gefunden: {config_path}")

    config_doc = json.loads(config_path.read_text(encoding="utf-8"))
    notes: list[str] = []
    batteries = config_doc.pop("batteries", None)
    pv_systems = config_doc.pop("pv_systems", None)
    if batteries is None and pv_systems is None:
        notes.append("Keine batteries/pv_systems in config.json — nichts zu migrieren.")
        return notes

    components_doc: dict = {"batteries": [], "pv_systems": []}
    if components_path.is_file():
        existing = json.loads(components_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            components_doc = existing

    if batteries is not None:
        components_doc["batteries"] = batteries
        notes.append(f"{len(batteries)} Batterie(n) nach components.json übernommen.")
    if pv_systems is not None:
        components_doc["pv_systems"] = pv_systems
        notes.append(f"{len(pv_systems)} PV-Anlage(n) nach components.json übernommen.")

    if not components_doc.get("$schema"):
        components_doc = {
            "$schema": "./components.schema.json",
            **{k: v for k, v in components_doc.items() if k != "$schema"},
        }

    if dry_run:
        notes.append(f"[dry-run] Würde schreiben: {components_path}")
        notes.append(f"[dry-run] Würde aktualisieren: {config_path}")
        return notes

    components_path.write_text(
        json.dumps(components_doc, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(config_doc, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config_dir",
        nargs="?",
        type=Path,
        default=ROOT / "config",
        help="Verzeichnis mit config.json (Standard: config/)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        notes = migrate_config_dir(args.config_dir.resolve(), dry_run=args.dry_run)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
