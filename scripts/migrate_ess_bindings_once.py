"""One-off: move plant-flat ESS bindings onto batteries (2.7.m / Quellenwahl).

Thin wrapper — prefer ``python -m scripts.migrate_config``.
"""
from __future__ import annotations

import argparse
import sys

from scripts._migrate_cli_common import configure_console_utf8, run_config_migration


def main(argv: list[str] | None = None) -> int:
    configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Move plant-flat ESS ehal_bindings onto batteries "
            "(entity-scoped ess.{slug}.*); move set_ess_source_select onto "
            "the physical standby_backup battery."
        )
    )
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run_config_migration(args.config_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
