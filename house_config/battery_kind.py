"""Deprecated topology kinds (2.7.c) — replaced by inverters[].ac_connection (2.7.l).

Kept as a thin shim for any remaining imports during Inverter P2 UI cleanup.
"""
from __future__ import annotations

from typing import Literal

from house_config.inverter import AC_ISLAND, allows_automatik as _allows_automatik_ac

BatteryKind = Literal["isolated", "battery_inverter"]

BATTERY_KIND_ISOLATED: BatteryKind = "isolated"
BATTERY_KIND_BATTERY_INVERTER: BatteryKind = "battery_inverter"
DEFAULT_BATTERY_KIND: BatteryKind = BATTERY_KIND_BATTERY_INVERTER

_ALLOWED: frozenset[str] = frozenset(
    {BATTERY_KIND_ISOLATED, BATTERY_KIND_BATTERY_INVERTER}
)


def normalize_battery_kind(
    raw: object, *, battery_id: str, index: int
) -> BatteryKind:
    raise ValueError(
        f"batteries[{index}] ('{battery_id}'): field 'kind' is removed (2.7.l). "
        "Use inverters[].ac_connection; run "
        "python -m scripts.migrate_inverters_once --config-dir <config-dir>"
    )


def allows_automatik(kind_or_ac: str) -> bool:
    """Compat: ``isolated`` / ``island`` → False; else True."""
    value = str(kind_or_ac or "").strip().lower()
    if value == BATTERY_KIND_ISOLATED or value == AC_ISLAND:
        return False
    return _allows_automatik_ac(value if value in ("grid_tied", "island") else "grid_tied")
