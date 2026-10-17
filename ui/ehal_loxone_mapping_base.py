"""Leaf constants/helpers shared by the Loxone EHAL mapping modules."""
from __future__ import annotations

_SESSION_MIGRATED = "ehal_lox_migrated_once"

PLANT_ENTITY_ID = "plant"
BATTERY_ENTITY_KIND = "battery"
INVERTER_ENTITY_KIND = "inverter"
PV_ENTITY_KIND = "pv_system"


def _nonempty(value: object) -> str:
    return str(value or "").strip()
