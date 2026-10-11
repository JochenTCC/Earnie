"""Migrate house_profiles (+ optional config) to ehal_bindings-only Merker addresses.

Usage:
  python -m scripts.migrate_ehal_bindings --path earnie_env/config/house_profiles.json
  python -m scripts.migrate_ehal_bindings --path PATH --config PATH/config.json --dry-run
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
    with path.open(encoding="utf-8") as handle:  # NOSONAR pythonsecurity:S8707
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    return doc


def _write_json(path: Path, doc: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:  # NOSONAR pythonsecurity:S8707
        json.dump(doc, handle, ensure_ascii=False, indent=4)
        handle.write("\n")


def main(argv: list[str] | None = None) -> None:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy Loxone Merker nests and flat ehal.ha.entities "
            "→ plant/consumer ehal_bindings; strip leftovers."
        )
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Path to house_profiles.json",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Optional config.json (strips migrated loxone_blocks / ehal.ha.entities)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print whether changes would be written without saving",
    )
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Migrate bindings but do not strip legacy nests",
    )
    args = parser.parse_args(argv)

    from house_config.ehal_bindings import (
        ensure_migrated,
        migrate_loxone_blocks_to_plant,
        strip_migrated_config_keys,
    )

    house_path = Path(args.path)
    house_doc = _load_json(house_path)
    config_doc: dict | None = None
    config_path: Path | None = None
    if args.config:
        config_path = Path(args.config)
        config_doc = _load_json(config_path)

    # Explicit CLI migrate: blocks → plant before ensure_migrated (which refuses blocks).
    if isinstance(config_doc, dict):
        blocks = config_doc.get("loxone_blocks")
        if isinstance(blocks, dict) and blocks:
            house_doc = dict(house_doc)
            plant = dict(house_doc.get("plant") or {}) if isinstance(
                house_doc.get("plant"), dict
            ) else {}
            bindings = dict(plant.get("ehal_bindings") or {}) if isinstance(
                plant.get("ehal_bindings"), dict
            ) else {}
            for field, addr in migrate_loxone_blocks_to_plant(blocks).items():
                if field not in bindings or not str(bindings.get(field) or "").strip():
                    bindings[field] = addr
            plant["ehal_bindings"] = bindings
            house_doc["plant"] = plant
            config_doc = dict(config_doc)
            config_doc.pop("loxone_blocks", None)

    house_out, config_out, changed = ensure_migrated(
        house_doc,
        config_doc,
        strip_legacy=not args.keep_legacy,
    )
    config_changed = False
    if config_path is not None:
        stripped = strip_migrated_config_keys(config_out)
        if stripped != config_doc:
            config_out = stripped
            config_changed = True
            changed = True

    if args.dry_run:
        print(f"dry-run: house_changed={changed and house_out != house_doc} "
              f"config_changed={config_changed} path={house_path}")
    else:
        if house_out != house_doc:
            _write_json(house_path, house_out)
            print(f"Wrote {house_path}")
        else:
            print(f"No house_profiles changes: {house_path}")
        if config_path is not None and config_changed:
            _write_json(config_path, config_out)
            print(f"Wrote {config_path}")


if __name__ == "__main__":
    main()
