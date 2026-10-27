"""House-profile field ``netznutzung``: grid area selection (Edibert prices it since P3b).

The grid-fee catalog (``grid_fees.json``) and the user grid areas (``user_grid_fees.json``)
are loaded and evaluated by Edibert (``house_config/edibert_tariffs.py``,
``data/edibert_slot_prices.py``). Here only the profile field is checked and defaulted.
"""
from __future__ import annotations

from typing import Any

STATUS_VERORDNET = "verordnet"
STATUS_ENTWURF = "entwurf"
STATUS_ILLUSTRATIV = "illustrativ"
VALID_STATUS = frozenset({STATUS_VERORDNET, STATUS_ENTWURF, STATUS_ILLUSTRATIV})

METERING_UNMETERED = "unmetered_power"

# Edibert ``requires`` vocabulary met by the same assumption as ``quarter_hour_meter: True``
# below (QH smart meter, not an Earnie configuration). ``separate_meter`` and
# ``controllable_device`` have no Earnie field and are never claimed.
ASSUMED_METER_CAPABILITIES = ("smart_meter", "quarter_hour_meter")

DEFAULT_INCLUDE_STATUS = (STATUS_VERORDNET,)

_MIGRATE_HINT = (
    "Konfiguration migrieren: Streamlit-Seite „Konfigurations-Migration“ oder "
    "python -m scripts.migrate_config --config-dir <config> (Datenmodell 5)"
)


def default_netznutzung_config() -> dict[str, Any]:
    """Form default for a new house profile; ``area_id`` must still be chosen."""
    return {
        "area_id": None,
        "power_metering": METERING_UNMETERED,
        # Assumed present — not an Earnie configuration (SNAP/WiNAP catalog requires).
        "quarter_hour_meter": True,
        "include_status": list(DEFAULT_INCLUDE_STATUS),
    }


def normalize_netznutzung_config(raw: Any, *, label: str = "netznutzung") -> dict[str, Any]:
    """Validiert das Profilfeld ``netznutzung``: Netzbereich Pflicht, kein eigener Basiswert.

    Ein eigener Arbeitspreis ist seit Datenmodell 5 ein Benutzer-Netzbereich
    (``user_grid_fees.json``); alte Profile (``area_id: null`` / ``base_cent_kwh``) brechen
    mit Migrationshinweis ab.
    """
    if raw is None:
        raise ValueError(f"{label} fehlt (Netzbereich ist Pflicht) — {_MIGRATE_HINT}.")
    if not isinstance(raw, dict):
        raise ValueError(f"{label} muss ein Objekt sein.")
    if "base_cent_kwh" in raw:
        raise ValueError(
            f"{label}.base_cent_kwh wird nicht mehr unterstützt (eigener Arbeitspreis ist "
            f"ein Benutzer-Netzbereich) — {_MIGRATE_HINT}."
        )
    area_raw = raw.get("area_id")
    area_id = str(area_raw).strip() if area_raw not in (None, "") else None
    if area_id is None:
        raise ValueError(f"{label}.area_id fehlt (Netzbereich ist Pflicht) — {_MIGRATE_HINT}.")
    include_raw = raw.get("include_status", list(DEFAULT_INCLUDE_STATUS))
    if not isinstance(include_raw, list):
        raise ValueError(f"{label}.include_status muss eine Liste sein.")
    include = [str(item).strip().lower() for item in include_raw]
    for item in include:
        if item not in VALID_STATUS:
            raise ValueError(
                f"{label}.include_status '{item}' ungültig. "
                f"Erlaubt: {', '.join(sorted(VALID_STATUS))}."
            )
    return {
        "area_id": area_id,
        # Assumed household unmetered — not an Earnie configuration.
        "power_metering": METERING_UNMETERED,
        "quarter_hour_meter": True,
        "include_status": include,
    }
