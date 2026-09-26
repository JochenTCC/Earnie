"""HA vendor ESS force (e.g. huawei_solar forcible charge/discharge services)."""
from __future__ import annotations

from typing import Any

HUAWEI_SOLAR_DRIVER = "huawei_solar"
DEFAULT_FORCE_DURATION_MIN = 20
MAX_FORCE_DURATION_MIN = 1440

SUPPORTED_ESS_FORCE_DRIVERS = frozenset({HUAWEI_SOLAR_DRIVER})


def normalize_ha_ess_force(raw: object) -> dict[str, Any] | None:
    """Normalize ``plant.ha_ess_force``; return None when absent/empty."""
    if not isinstance(raw, dict) or not raw:
        return None
    driver = str(raw.get("driver") or "").strip().lower()
    device_id = str(raw.get("device_id") or "").strip()
    if not driver and not device_id:
        return None
    if driver not in SUPPORTED_ESS_FORCE_DRIVERS:
        raise ValueError(
            f"plant.ha_ess_force.driver muss einer von "
            f"{sorted(SUPPORTED_ESS_FORCE_DRIVERS)} sein (got {raw.get('driver')!r})."
        )
    if not device_id:
        raise ValueError("plant.ha_ess_force.device_id fehlt.")
    duration = int(raw.get("duration_min", DEFAULT_FORCE_DURATION_MIN) or DEFAULT_FORCE_DURATION_MIN)
    if duration < 1 or duration > MAX_FORCE_DURATION_MIN:
        raise ValueError(
            f"plant.ha_ess_force.duration_min muss in 1..{MAX_FORCE_DURATION_MIN} liegen."
        )
    return {
        "driver": driver,
        "device_id": device_id,
        "duration_min": duration,
    }


def ha_ess_force_enables_ess_active(ha_ess_force: dict[str, Any] | None) -> bool:
    """True when vendor force config is enough for ess_active without an entity."""
    if not isinstance(ha_ess_force, dict):
        return False
    driver = str(ha_ess_force.get("driver") or "").strip().lower()
    device_id = str(ha_ess_force.get("device_id") or "").strip()
    return driver in SUPPORTED_ESS_FORCE_DRIVERS and bool(device_id)
