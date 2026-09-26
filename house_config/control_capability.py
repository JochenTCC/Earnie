"""Cross-check batteries[].control against bound EHAL functions."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ehal.functions import available_functions
from house_config.battery_control import (
    BATTERY_CONTROL_FULL,
    BATTERY_CONTROL_LIMITS_ONLY,
    BATTERY_CONTROL_READ_ONLY,
    control_from_battery_params,
)
from house_config.ha_ess_force import ha_ess_force_enables_ess_active


def control_capability_warnings(
    *,
    control: str | None,
    ehal_map: Mapping[str, object] | None,
    ha_ess_force: dict[str, Any] | None = None,
) -> list[str]:
    """German warnings when ``control`` asks for more than the mapping allows."""
    level = control_from_battery_params({"control": control})
    if level == BATTERY_CONTROL_READ_ONLY:
        return []

    vendor = ha_ess_force_enables_ess_active(ha_ess_force)
    available = available_functions(ehal_map or {}, vendor_ess_active=vendor)
    warnings: list[str] = []

    if level == BATTERY_CONTROL_FULL and "ess_active" not in available:
        warnings.append(
            "Steuerbarkeit „full“ erfordert Zwangsladen/-entladen "
            "(set_ess_active_power oder plant.ha_ess_force), "
            "aber die Funktion „Speicher zwingen“ ist nicht verfügbar."
        )
    if level in (BATTERY_CONTROL_FULL, BATTERY_CONTROL_LIMITS_ONLY) and (
        "ess_limits" not in available
    ):
        warnings.append(
            "Steuerbarkeit erfordert Lade-/Entladegrenzen "
            "(set_ess_charge/discharge_power_limit), "
            "aber die Funktion „Speicher begrenzen“ ist nicht verfügbar."
        )
    return warnings
