#!/usr/bin/env python3
"""Print hardware fingerprint and identity part keys (2.4.i spike)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_store.hardware_identity import (
    collect_and_fingerprint,
    display_fingerprint,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print Earnie hardware fingerprint (registry spike).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print full 64-char fingerprint (default: short display + full)",
    )
    args = parser.parse_args(argv)
    parts, fingerprint = collect_and_fingerprint()
    present = [key for key, value in parts.items() if str(value).strip()]
    print(f"fingerprint_display={display_fingerprint(fingerprint)}")
    print(f"fingerprint={fingerprint}")
    print(f"parts_present={','.join(present) if present else '(none)'}")
    if args.full:
        for key in sorted(parts):
            # Do not print raw host/southbound IDs by default beyond presence.
            print(f"part_set.{key}={'yes' if str(parts[key]).strip() else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
