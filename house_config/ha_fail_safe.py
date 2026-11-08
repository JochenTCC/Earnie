"""Values the HA package writes while Earnie is unreachable (``plant.ha_fail_safe_values``).

What is safe depends on the device, so the user enters the values. They are stored per
qualified write ID in canonical EHAL units (W, A); the HA package converts them to the
entity's unit at run time. A signal without a value is left alone.
"""
from __future__ import annotations

import math

from ehal.push_signals import is_valid_write_ehal_id
from ehal.qualified_ids import field_kind

FAIL_SAFE_VALUES_KEY = "ha_fail_safe_values"
# Signed by design; every other signal with a unit is a limit, which cannot be negative.
SIGNED_FAIL_SAFE_KINDS = frozenset({"set_ess_active_power"})


def is_signed_fail_safe(ehal_id: str) -> bool:
    return field_kind(ehal_id) in SIGNED_FAIL_SAFE_KINDS


def _validated_value(ehal_id: str, value: object) -> float:
    label = f"plant.{FAIL_SAFE_VALUES_KEY}[{ehal_id!r}]"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} muss eine Zahl sein (got {value!r}).")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} muss endlich sein (got {value!r}).")
    if number < 0.0 and not is_signed_fail_safe(ehal_id):
        raise ValueError(f"{label} muss >= 0 sein (got {value!r}).")
    return number


def normalize_ha_fail_safe_values(raw: object) -> dict[str, float] | None:
    """Validated ``plant.ha_fail_safe_values``; ``None`` when absent or empty."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"plant.{FAIL_SAFE_VALUES_KEY} muss ein Objekt sein.")
    out: dict[str, float] = {}
    for key, value in raw.items():
        ehal_id = str(key)
        if not is_valid_write_ehal_id(ehal_id):
            raise ValueError(f"plant.{FAIL_SAFE_VALUES_KEY}: {ehal_id!r} ist kein set_*-Signal.")
        out[ehal_id] = _validated_value(ehal_id, value)
    return out or None


def house_with_fail_safe_values(house: dict, entered: dict[str, float | None]) -> dict:
    """Copy of ``house`` whose plant holds exactly the values in ``entered`` that are set."""
    values = {key: value for key, value in entered.items() if value is not None}
    plant = dict(house.get("plant") or {})
    normalized = normalize_ha_fail_safe_values(values)
    if normalized:
        plant[FAIL_SAFE_VALUES_KEY] = normalized
    else:
        plant.pop(FAIL_SAFE_VALUES_KEY, None)
    return {**house, "plant": plant}
