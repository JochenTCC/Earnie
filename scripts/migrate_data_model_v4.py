"""Migrate Earnie config directory from earnie_data_model 3 → 4 (2.7.c).

Thin wrapper — prefer ``python -m scripts.migrate_config``.

Usage:
  python -m scripts.migrate_data_model_v4 --config-dir earnie_env/config
  python -m scripts.migrate_data_model_v4 --config-dir PATH --dry-run
"""
from __future__ import annotations

import argparse
import sys

from scripts._migrate_cli_common import configure_console_utf8, run_config_migration


def main(argv: list[str] | None = None) -> int:
    configure_console_utf8()
    parser = argparse.ArgumentParser(
        description="Migrate config JSON docs earnie_data_model 3 → 4 (multi-ESS)."
    )
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run_config_migration(args.config_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
