"""Migrate Earnie config directory from earnie_data_model 3 → 4 (2.7.c).

Usage:
  python -m scripts.migrate_data_model_v4 --config-dir earnie_env/config
  python -m scripts.migrate_data_model_v4 --config-dir PATH --dry-run
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


_FILES = (
    "config.json",
    "backtesting_scenarios.json",
    "components.json",
    "deviation_rules.json",
    "house_profiles.json",
    "tariffs.json",
)


def main(argv: list[str] | None = None) -> None:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description="Migrate config JSON docs earnie_data_model 3 → 4 (multi-ESS)."
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        help="Directory containing config.json / components.json / …",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing",
    )
    args = parser.parse_args(argv)

    from runtime_store.migrate_v4 import migrate_pack_docs

    root = Path(args.config_dir)
    docs: dict[str, dict] = {}
    for name in _FILES:
        path = root / name
        if path.is_file():
            docs[name] = _load_json(path)

    if not docs:
        raise SystemExit(f"No config JSON files found in {root}")

    migrated = migrate_pack_docs(docs)
    for name, doc in migrated.items():
        path = root / name
        if args.dry_run:
            print(f"dry-run: would write {path}")
            continue
        _write_json(path, doc)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
