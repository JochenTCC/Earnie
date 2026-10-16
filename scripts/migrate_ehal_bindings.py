"""Migrate house_profiles (+ optional config) to ehal_bindings-only Merker addresses.

Thin wrapper — prefer ``python -m scripts.migrate_config``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts._migrate_cli_common import configure_console_utf8, run_config_migration


def main(argv: list[str] | None = None) -> None:
    configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy Loxone Merker nests and flat ehal.ha.entities "
            "→ plant/consumer ehal_bindings; strip leftovers."
        )
    )
    parser.add_argument("--path", required=True, help="Path to house_profiles.json")
    parser.add_argument("--config", default="", help="Optional config.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Ignored (registry always strips legacy nests in pack chain).",
    )
    args = parser.parse_args(argv)
    config_dir = Path(args.path).parent
    return run_config_migration(config_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
