#!/usr/bin/env python3
"""Erzeugt Entwürfe für ID-only runtime_settings (1.26.0 P5)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from house_config.migrate_runtime_entities import migrate_runtime_entities, write_migration_draft

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Datei '{path}' ist weder UTF-8 noch cp1252 lesbar.")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Migriert flache runtime_settings in Entitäts-Referenzen (Entwurf)."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "config" / "config.json",
        help="Quell-config.json (Standard: config/config.json)",
    )
    parser.add_argument(
        "--tariffs",
        type=Path,
        default=None,
        help="Quell-tariffs.json (Standard: neben --input)",
    )
    parser.add_argument(
        "--house-profiles",
        type=Path,
        default=None,
        help="Quell-house_profiles.json (Standard: neben --input)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Zielordner für Entwurfsdateien (wird nicht überschrieben ohne --force)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bestehenden --output-dir überschreiben",
    )
    args = parser.parse_args(argv)

    config_path = args.input.resolve()
    config_dir = config_path.parent
    tariffs_path = (args.tariffs or config_dir / "tariffs.json").resolve()
    profiles_path = (args.house_profiles or config_dir / "house_profiles.json").resolve()
    output_dir = args.output_dir.resolve()

    if not config_path.is_file():
        print(f"Fehler: config.json nicht gefunden: {config_path}", file=sys.stderr)
        return 1
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force:
        print(
            f"Fehler: {output_dir} ist nicht leer — --force verwenden oder anderen Ordner wählen.",
            file=sys.stderr,
        )
        return 1

    config = _read_json(config_path)
    tariffs_doc = _read_json(tariffs_path) if tariffs_path.is_file() else {
        "import_tariffs": [],
        "export_tariffs": [],
    }
    profiles_doc = _read_json(profiles_path) if profiles_path.is_file() else {"profiles": []}

    migrated_config, migrated_tariffs, migrated_profiles, notes = migrate_runtime_entities(
        config,
        tariffs_doc=tariffs_doc,
        house_profiles_doc=profiles_doc,
    )
    write_migration_draft(
        output_dir,
        config=migrated_config,
        tariffs_doc=migrated_tariffs,
        house_profiles_doc=migrated_profiles,
        notes=notes,
    )

    runtime = migrated_config.get("runtime_settings", {})
    print(f"Entwurf geschrieben nach: {output_dir}")
    print(f"  runtime_settings IDs: {', '.join(f'{k}={runtime.get(k)!r}' for k in sorted(runtime))}")
    if notes:
        print("Hinweise:")
        for note in notes:
            print(f"  - {note}")
    print("Bitte MIGRATION_REVIEW.md lesen und manuell prüfen vor Deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
