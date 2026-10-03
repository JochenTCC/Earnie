"""Battery topology kinds (2.7.c): isolated vs battery+inverter."""
from __future__ import annotations

from typing import Literal

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
    if raw is None or raw == "":
        return DEFAULT_BATTERY_KIND
    kind = str(raw).strip().lower()
    if kind not in _ALLOWED:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): kind muss "
            f"'isolated' oder 'battery_inverter' sein (got {raw!r})."
        )
    return kind  # type: ignore[return-value]


def allows_automatik(kind: str) -> bool:
    """True when Design C1 Automatik / optimizing mode is allowed."""
    return str(kind or "").strip().lower() != BATTERY_KIND_ISOLATED
