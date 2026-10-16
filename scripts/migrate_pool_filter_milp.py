"""Promote pool_filter MILP fields / rewrite deviation scopes.

Thin wrapper — prefer ``python -m scripts.migrate_config``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts._migrate_cli_common import configure_console_utf8, run_config_migration


def main(argv: list[str] | None = None) -> int:
    configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", required=True, help="Path to house_profiles.json")
    parser.add_argument("--deviation", default="", help="Optional deviation_rules.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    config_dir = Path(args.path).parent
    return run_config_migration(config_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
