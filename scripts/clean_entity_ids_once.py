"""One-off: rename dirty battery/PV ids from Bezeichnung in an earnie_env.

Usage (dry-run by default — no writes):
  python -m scripts.clean_entity_ids_once --config-dir earnie_env/config
  python -m scripts.clean_entity_ids_once --config-dir PATH --apply
  python -m scripts.clean_entity_ids_once --config-dir PATH --only-copy --apply

Rewrites ``components.json`` ids, Pattern B ``ehal_bindings``, scenario
``battery_ids`` / ``pv_system_ids``, and ``powerstation_id`` on reserve
consumers in ``house_profiles.json``. Sets ``id_locked: true`` on renamed
entities.
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
            "Rename battery/PV ids that differ from slug(Bezeichnung); "
            "lock afterwards. Dry-run unless --apply."
        )
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        help="Directory with components.json (+ scenarios / house_profiles)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default is dry-run)",
    )
    parser.add_argument(
        "--only-copy",
        action="store_true",
        help="Only rename ids that contain '_copy' (UI clone leftovers)",
    )
    args = parser.parse_args(argv)

    from house_config.clean_entity_ids import apply_clean_entity_ids

    root = Path(args.config_dir)
    components_path = root / "components.json"
    scenarios_path = root / "backtesting_scenarios.json"
    house_path = root / "house_profiles.json"
    if not components_path.is_file():
        raise SystemExit(f"Missing {components_path}")

    components = _load_json(components_path)
    scenarios = _load_json(scenarios_path) if scenarios_path.is_file() else None
    house = _load_json(house_path) if house_path.is_file() else None

    comp_out, scen_out, house_out, renames = apply_clean_entity_ids(
        components,
        scenarios,
        house,
        only_copy=bool(args.only_copy),
    )
    if not renames:
        print("No dirty battery/PV ids to rename; nothing to do.")
        return

    for item in renames:
        print(f"{item.kind}: {item.old_id} → {item.new_id}  (label={item.label!r})")

    if not args.apply:
        print("dry-run: pass --apply to write components/scenarios/house_profiles")
        return

    _write_json(components_path, comp_out)
    print(f"Wrote {components_path}")
    if scen_out is not None and scenarios_path.is_file():
        _write_json(scenarios_path, scen_out)
        print(f"Wrote {scenarios_path}")
    if house_out is not None and house_path.is_file():
        _write_json(house_path, house_out)
        print(f"Wrote {house_path}")


if __name__ == "__main__":
    main()
