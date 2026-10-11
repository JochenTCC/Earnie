"""Migrate house_profiles.json: netznutzung_arbeitspreis_cent_kwh -> netznutzung object.

The flat value becomes a manual base (no catalog area, no time rules), so prices
stay identical. Assign a Netzbereich (SNAP/WiNAP rules) afterwards in the Hausprofil
form or via ``--area-id`` (applies to every migrated profile).

Usage:
  python -m scripts.migrate_grid_fee_profile --path earnie_env/config/house_profiles.json
  python -m scripts.migrate_grid_fee_profile --path PATH --area-id AT-VBG --quarter-hour-meter
  python -m scripts.migrate_grid_fee_profile --path PATH --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LEGACY_KEY = "netznutzung_arbeitspreis_cent_kwh"


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def migrate_profile(
    profile: dict,
    *,
    area_id: str | None = None,
    quarter_hour_meter: bool = False,
) -> bool:
    """Replace the legacy scalar in place. Returns True when the profile changed."""
    if LEGACY_KEY not in profile:
        return False
    legacy = float(profile.pop(LEGACY_KEY) or 0.0)
    if legacy < 0.0:
        raise ValueError(f"profile '{profile.get('id')}': {LEGACY_KEY} muss >= 0 sein.")
    if "netznutzung" in profile:
        raise ValueError(
            f"profile '{profile.get('id')}': hat {LEGACY_KEY} und 'netznutzung' - bitte manuell klären."
        )
    profile["netznutzung"] = {
        "area_id": area_id,
        "power_metering": "unmetered_power",
        "quarter_hour_meter": bool(quarter_hour_meter),
        "base_cent_kwh": legacy,
        "include_status": ["verordnet"],
    }
    return True


def migrate_document(doc: dict, **kwargs) -> int:
    profiles = doc.get("profiles", [])
    items = profiles.values() if isinstance(profiles, dict) else profiles
    return sum(1 for item in items if isinstance(item, dict) and migrate_profile(item, **kwargs))


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", required=True, help="Path to house_profiles.json")
    parser.add_argument("--area-id", default=None, help="Netzbereich-ID aus grid_fees.json")
    parser.add_argument("--quarter-hour-meter", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.path)
    with path.open(encoding="utf-8") as handle:  # NOSONAR pythonsecurity:S8707
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    changed = migrate_document(
        doc, area_id=args.area_id, quarter_hour_meter=args.quarter_hour_meter
    )
    print(f"{changed} Profil(e) migriert.")
    if changed and not args.dry_run:
        with path.open("w", encoding="utf-8", newline="\n") as handle:  # NOSONAR pythonsecurity:S8707
            json.dump(doc, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
