"""Migrate house_profiles.json: netznutzung_arbeitspreis_cent_kwh -> netznutzung object.

Thin wrapper — prefer ``python -m scripts.migrate_config``.
Apply helpers live in ``house_config.migrate_grid_fee`` (re-exported here for tests).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from house_config.migrate_grid_fee import (  # noqa: F401 — re-export for tests
    LEGACY_KEY,
    migrate_document,
    migrate_profile,
)
from scripts._migrate_cli_common import configure_console_utf8, run_config_migration


def main(argv: list[str] | None = None) -> int:
    configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", required=True, help="Path to house_profiles.json")
    parser.add_argument("--area-id", default=None, help="Netzbereich-ID aus grid_fees.json")
    parser.add_argument("--quarter-hour-meter", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from runtime_store.migration.steps.grid_fee_profile import Q_AREA, Q_QHM

    answers = {
        Q_AREA: args.area_id,
        Q_QHM: bool(args.quarter_hour_meter),
    }
    return run_config_migration(
        Path(args.path).parent, dry_run=args.dry_run, answers=answers
    )


if __name__ == "__main__":
    raise SystemExit(main())
