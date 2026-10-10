"""One-off: move plant-flat ESS bindings onto batteries (2.7.m / Quellenwahl).

Usage:
  python -m scripts.migrate_ess_bindings_once --config-dir earnie_env/config
  python -m scripts.migrate_ess_bindings_once --config-dir PATH --dry-run

Phase 1: movable plant-flat ESS → single battery Pattern B ``ess.{slug}.*``.
Phase 2: plant ``set_ess_source_select`` → physical ``standby_backup``
``ess.{id}.set_ess_source_select``. Stays on ``earnie_data_model`` 4.
Delete this script after successful env migration.
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


def main(argv: list[str] | None = None) -> None:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Move plant-flat ESS ehal_bindings onto batteries "
            "(Pattern B ess.{slug}.*); move set_ess_source_select onto "
            "the physical standby_backup battery."
        )
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        help="Directory containing house_profiles.json / components.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing",
    )
    args = parser.parse_args(argv)

    from runtime_store.migrate_v4 import (
        MigrateV4Error,
        migrate_plant_ess_to_components,
        migrate_plant_source_select_to_standby,
        residual_plant_flat_ess_keys,
    )

    root = Path(args.config_dir)
    house_path = root / "house_profiles.json"
    components_path = root / "components.json"
    if not house_path.is_file():
        raise SystemExit(f"Missing {house_path}")
    if not components_path.is_file():
        raise SystemExit(f"Missing {components_path}")

    house = _load_json(house_path)
    components = _load_json(components_path)
    try:
        house_out, comp_out, changed_ess = migrate_plant_ess_to_components(
            house, components, label=str(house_path)
        )
        house_out, comp_out, changed_src = migrate_plant_source_select_to_standby(
            house_out, comp_out, label=str(house_path)
        )
    except MigrateV4Error as exc:
        raise SystemExit(str(exc)) from exc

    residual = residual_plant_flat_ess_keys(house_out)
    if residual:
        raise SystemExit(
            "Plant still has flat ESS bindings after migrate: "
            f"{', '.join(residual)}. "
            "Move them to batteries[].ehal_bindings (ess.{{slug}}.*) manually "
            "or reduce to a single battery / one physical standby_backup."
        )

    changed = changed_ess or changed_src
    if not changed:
        print("No plant-flat ESS / Quellenwahl bindings to move; nothing to do.")
        return

    if args.dry_run:
        print(f"dry-run: would write {house_path}")
        print(f"dry-run: would write {components_path}")
        return

    _write_json(house_path, house_out)
    _write_json(components_path, comp_out)
    print(f"Wrote {house_path}")
    print(f"Wrote {components_path}")


if __name__ == "__main__":
    main()
