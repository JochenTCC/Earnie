"""Promote pool_filter MILP shape; strip swimspa_filter_bindings nests.

Usage:
  python -m scripts.migrate_pool_filter_milp --path earnie_env/config/house_profiles.json
  python -m scripts.migrate_pool_filter_milp --path PATH --deviation PATH/deviation_rules.json
  python -m scripts.migrate_pool_filter_milp --path PATH --dry-run
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


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description="Promote pool_filter off synthetic swimspa_filter bridge."
    )
    parser.add_argument("--path", required=True, help="Path to house_profiles.json")
    parser.add_argument(
        "--deviation",
        default="",
        help="Optional deviation_rules.json (rewrite scope swimspa_filter → pool_filter)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes/warnings without writing",
    )
    args = parser.parse_args(argv)

    from house_config.migrate_pool_filter import (
        promote_pool_filter_milp,
        rewrite_deviation_filter_scopes,
    )

    house_path = Path(args.path)
    house_doc = _load_json(house_path)
    house_out, changed, warnings = promote_pool_filter_milp(house_doc)

    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)

    deviation_changed = False
    deviation_out: dict | None = None
    deviation_path: Path | None = None
    if args.deviation:
        deviation_path = Path(args.deviation)
        deviation_out, deviation_changed = rewrite_deviation_filter_scopes(
            _load_json(deviation_path)
        )

    if args.dry_run:
        print(
            f"dry-run: house_changed={changed} deviation_changed={deviation_changed} "
            f"warnings={len(warnings)}"
        )
        return 1 if warnings else 0

    if changed:
        _write_json(house_path, house_out)
        print(f"Wrote {house_path}")
    else:
        print(f"No house_profiles changes: {house_path}")

    if deviation_path is not None and deviation_out is not None:
        if deviation_changed:
            _write_json(deviation_path, deviation_out)
            print(f"Wrote {deviation_path}")
        else:
            print(f"No deviation_rules changes: {deviation_path}")

    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
