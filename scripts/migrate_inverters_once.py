"""One-off: create inverters[] and drop batteries[].kind (2.7.l Inverter P1).

Usage:
  python -m scripts.migrate_inverters_once --config-dir earnie_env/config
  python -m scripts.migrate_inverters_once --config-dir PATH --dry-run

Creates hybrid ``wr_main`` (no max_ac_power_kw) for house batteries /
battery_inverter topology; each ``kind: isolated`` battery gets its own
island inverter. Attaches all PV systems to ``wr_main`` (or the battery's
island inverter when that is the only inverter). Stays on earnie_data_model 4.
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
        description="Create inverters[] and drop batteries[].kind (2.7.l)."
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

    from house_config.migrate_inverters import migrate_components_inverters

    root = Path(args.config_dir)
    components_path = root / "components.json"
    if not components_path.is_file():
        raise SystemExit(f"Missing {components_path}")

    components = _load_json(components_path)
    out, changed = migrate_components_inverters(components)
    if not changed:
        print("Already migrated (inverters[] present, no batteries[].kind); nothing to do.")
        return

    if args.dry_run:
        print(f"dry-run: would write {components_path}")
        print(f"  inverters: {len(out.get('inverters') or [])}")
        return

    _write_json(components_path, out)
    print(f"Wrote {components_path}")
    print(f"  inverters: {len(out.get('inverters') or [])}")


if __name__ == "__main__":
    main()
