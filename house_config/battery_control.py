"""Battery controllability levels (`batteries[].control`)."""
from __future__ import annotations

from typing import Literal

BatteryControl = Literal["full", "limits_only", "read_only"]

BATTERY_CONTROL_FULL: BatteryControl = "full"
BATTERY_CONTROL_LIMITS_ONLY: BatteryControl = "limits_only"
BATTERY_CONTROL_READ_ONLY: BatteryControl = "read_only"

BATTERY_CONTROL_VALUES: frozenset[str] = frozenset(
    {BATTERY_CONTROL_FULL, BATTERY_CONTROL_LIMITS_ONLY, BATTERY_CONTROL_READ_ONLY}
)

DEFAULT_BATTERY_CONTROL: BatteryControl = BATTERY_CONTROL_FULL

CONTROL_LABELS_DE: dict[str, str] = {
    BATTERY_CONTROL_FULL: "Voll steuerbar (Zwangsladen/-entladen)",
    BATTERY_CONTROL_LIMITS_ONLY: "Nur Grenzen (Automatik / Entladesperre)",
    BATTERY_CONTROL_READ_ONLY: "Nur lesen (Eigenverbrauch, keine Setpoints)",
}


def normalize_battery_control(raw: object, *, battery_id: str, index: int) -> BatteryControl:
    """Default ``full`` when missing; reject unknown strings."""
    if raw is None or raw == "":
        return DEFAULT_BATTERY_CONTROL
    value = str(raw).strip().lower()
    if value not in BATTERY_CONTROL_VALUES:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): control muss "
            f"{'|'.join(sorted(BATTERY_CONTROL_VALUES))} sein (got {raw!r})."
        )
    return value  # type: ignore[return-value]


def control_from_battery_params(battery_params: dict | None) -> BatteryControl:
    """Read ``control`` from optimizer battery_params (default full)."""
    if not battery_params:
        return DEFAULT_BATTERY_CONTROL
    raw = battery_params.get("control", DEFAULT_BATTERY_CONTROL)
    value = str(raw or DEFAULT_BATTERY_CONTROL).strip().lower()
    if value not in BATTERY_CONTROL_VALUES:
        return DEFAULT_BATTERY_CONTROL
    return value  # type: ignore[return-value]
