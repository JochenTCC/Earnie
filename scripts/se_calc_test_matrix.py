"""Materialize SE calc test matrix cells (inventory + temp overlays).

Examples:
  python -m scripts.se_calc_test_matrix --inventory
  python -m scripts.se_calc_test_matrix --cells M0,M1,M2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> None:
    _configure_console_utf8()
    from scripts.se_calc_test_common import (
        PRIORITIZED_CELLS,
        DESCRIPTORS_PATH,
        inventory_snapshot,
        materialize_cells,
        parse_csv_ids,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="Print Live/example_efh inventory and B-gate only",
    )
    parser.add_argument(
        "--cells",
        default=",".join(PRIORITIZED_CELLS),
        help="Comma-separated cell ids (default: M0,M1,M2)",
    )
    parser.add_argument(
        "--env",
        default=None,
        help="Env root (default: earnie_env)",
    )
    args = parser.parse_args(argv)
    env = Path(args.env) if args.env else None

    if args.inventory:
        snap = inventory_snapshot(env)
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        cell_ids = parse_csv_ids(args.cells, PRIORITIZED_CELLS)
        payload = materialize_cells(cell_ids, env)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\nWrote descriptors: {DESCRIPTORS_PATH}")


if __name__ == "__main__":
    main()
