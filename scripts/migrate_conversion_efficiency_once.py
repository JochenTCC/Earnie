"""One-off: add inverters[].efficiency and rewrite batteries[].battery_efficiency.

Usage:
  python -m scripts.migrate_conversion_efficiency_once --config-dir earnie_env/config
  python -m scripts.migrate_conversion_efficiency_once --config-dir PATH --dry-run

Treats today's battery_efficiency as lumped path η_old ≈ η_inv · η_batt.
Sets missing η_inv to 0.97 and η_batt = η_old / η_inv.
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
            "Add inverters[].efficiency (η_inv) and rewrite "
            "batteries[].battery_efficiency to η_batt."
        )
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        help="Directory containing components.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing",
    )
    args = parser.parse_args(argv)

    from house_config.migrate_conversion_efficiency import (
        migrate_components_conversion_efficiency,
    )

    root = Path(args.config_dir)
    components_path = root / "components.json"
    if not components_path.is_file():
        raise SystemExit(f"Missing {components_path}")

    components = _load_json(components_path)
    out, changed = migrate_components_conversion_efficiency(components)
    if not changed:
        print(
            "Already migrated (every inverter has efficiency); nothing to do."
        )
        return

    if args.dry_run:
        print(f"dry-run: would write {components_path}")
        for inv in out.get("inverters") or []:
            if isinstance(inv, dict):
                print(
                    f"  inverter {inv.get('id')}: efficiency={inv.get('efficiency')}"
                )
        for bat in out.get("batteries") or []:
            if isinstance(bat, dict):
                print(
                    f"  battery {bat.get('id')}: "
                    f"battery_efficiency={bat.get('battery_efficiency')}"
                )
        return

    _write_json(components_path, out)
    print(f"Wrote {components_path}")
    print(f"  inverters: {len(out.get('inverters') or [])}")
    print(f"  batteries: {len(out.get('batteries') or [])}")


if __name__ == "__main__":
    main()
