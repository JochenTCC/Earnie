"""Migrate house_profiles: netznutzung_arbeitspreis_cent_kwh → netznutzung object."""
from __future__ import annotations

from typing import Any

LEGACY_KEY = "netznutzung_arbeitspreis_cent_kwh"


def needs_grid_fee_profile_migration(doc: dict[str, Any] | None) -> bool:
    if not isinstance(doc, dict):
        return False
    profiles = doc.get("profiles")
    items = profiles.values() if isinstance(profiles, dict) else profiles
    if not isinstance(items, (list, tuple)):
        return False
    return any(isinstance(p, dict) and LEGACY_KEY in p for p in items)


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
            f"profile '{profile.get('id')}': hat {LEGACY_KEY} und 'netznutzung' — "
            "bitte manuell klären."
        )
    profile["netznutzung"] = {
        "area_id": area_id,
        "power_metering": "unmetered_power",
        "quarter_hour_meter": bool(quarter_hour_meter),
        "base_cent_kwh": legacy,
        "include_status": ["verordnet"],
    }
    return True


def migrate_document(
    doc: dict,
    *,
    area_id: str | None = None,
    quarter_hour_meter: bool = False,
) -> int:
    profiles = doc.get("profiles", [])
    items = profiles.values() if isinstance(profiles, dict) else profiles
    return sum(
        1
        for item in items
        if isinstance(item, dict)
        and migrate_profile(
            item, area_id=area_id, quarter_hour_meter=quarter_hour_meter
        )
    )
