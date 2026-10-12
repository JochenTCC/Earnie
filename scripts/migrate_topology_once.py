"""One-off Topology P1: house regulates_on + plant.grid_meter seed.

Usage:
  python -m scripts.migrate_topology_once --config-dir earnie_env/config
  python -m scripts.migrate_topology_once --config-dir PATH --dry-run

Sets batteries[].regulates_on = grid for every house battery missing it.
Seeds plant.grid_meter = {at_house_connection: true, single_tariff: true}
when absent and prints that the operator must confirm both assertions.
Data model stays 4.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    return doc


def _write_json(path: Path, doc: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=4)
        handle.write("\n")


_OPERATOR_CONFIRM = (
    "CONFIRM: plant.grid_meter was seeded true/true. Answer these before live:\n"
    "  1) Sitzt der Zähler direkt am Hausanschluss?\n"
    "  2) Gibt es nur einen Tarif?\n"
    "  3) Regelt ein anderes Gerät selbst auf diesen Zähler?\n"
    "Set at_house_connection / single_tariff to false (and fix the plant) "
    "if either assertion is wrong — the live path refuses otherwise."
)


def main(argv: list[str] | None = None) -> None:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Add batteries[].regulates_on (house) and seed plant.grid_meter "
            "(Topology P1)."
        )
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        help="Directory containing components.json and house_profiles.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing",
    )
    args = parser.parse_args(argv)

    from house_config.migrate_topology import (
        migrate_components_topology,
        migrate_house_profiles_grid_meter,
    )

    root = Path(args.config_dir)
    components_path = root / "components.json"
    profiles_path = root / "house_profiles.json"
    if not components_path.is_file():
        raise SystemExit(f"Missing {components_path}")

    any_change = False

    components = _load_json(components_path)
    components_out, migrated_ids = migrate_components_topology(components)
    if migrated_ids:
        any_change = True
        print("House batteries → regulates_on=grid:")
        for bat_id in migrated_ids:
            print(f"  - {bat_id}")
        if args.dry_run:
            print(f"dry-run: would write {components_path}")
        else:
            _write_json(components_path, components_out)
            print(f"Wrote {components_path}")
    else:
        print(
            "components: already migrated "
            "(every house battery has regulates_on)."
        )

    if profiles_path.is_file():
        profiles = _load_json(profiles_path)
        profiles_out, seeded = migrate_house_profiles_grid_meter(profiles)
        if seeded:
            any_change = True
            print(
                "plant.grid_meter → "
                "{at_house_connection: true, single_tariff: true}"
            )
            print(_OPERATOR_CONFIRM)
            if args.dry_run:
                print(f"dry-run: would write {profiles_path}")
            else:
                _write_json(profiles_path, profiles_out)
                print(f"Wrote {profiles_path}")
        else:
            print("house_profiles: plant.grid_meter already present.")
    else:
        print(f"Skip house_profiles (missing {profiles_path})")

    if not any_change:
        print("Nothing to do.")


if __name__ == "__main__":
    main()
