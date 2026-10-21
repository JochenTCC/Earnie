"""Plausibility bounds for pushed power values (HA testbed F21).

A unit mix-up at the source (kW sent as W) is not caught by the push contract: the
value is a valid number. Bound every pushed power by the configured hardware instead
and fail loud — no silent clamp, no silent skip of a value that is merely suspicious.

Only quantities with a configured reference are checked (inverter PV input / AC rating,
PV kWp, battery charge / discharge power). The grid power has no configured reference
and is not checked here.
"""
from __future__ import annotations

from typing import Any

# Generous: real peaks stay below ~1.3 x kWp; a kW/W mix-up is off by a factor of 1000.
POWER_BOUND_FACTOR = 3.0


class ImplausiblePowerError(ValueError):
    """A pushed power value exceeds what the configured hardware can deliver."""


def _positive_kw(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0.0 else 0.0


def inverter_pv_reference_kw(inverter: dict, pv_systems: list[dict]) -> float | None:
    """Largest known PV-side reference of an inverter (kW), ``None`` when none is configured."""
    iid = str(inverter.get("id") or "").strip()
    attached_kwp = sum(
        _positive_kw(pv.get("kwp"))
        for pv in pv_systems
        if isinstance(pv, dict) and str(pv.get("inverter_id") or "").strip() == iid
    )
    reference = max(
        _positive_kw(inverter.get("max_pv_input_kw")),
        _positive_kw(inverter.get("max_ac_power_kw")),
        attached_kwp,
    )
    return reference or None


def pv_system_reference_kw(pv_system: dict) -> float | None:
    return _positive_kw(pv_system.get("kwp")) or None


def battery_reference_kw(battery: dict) -> float | None:
    reference = max(
        _positive_kw(battery.get("battery_max_charge_power_kw")),
        _positive_kw(battery.get("battery_max_discharge_power_kw")),
    )
    return reference or None


def check_power_w(
    field: str,
    value_w: float,
    reference_kw: float | None,
    *,
    what: str,
) -> None:
    """Raise :class:`ImplausiblePowerError` when ``|value_w|`` exceeds the bound."""
    if reference_kw is None:
        return
    bound_w = POWER_BOUND_FACTOR * reference_kw * 1000.0
    if abs(float(value_w)) <= bound_w:
        return
    raise ImplausiblePowerError(
        f"Implausible value for {field}: {float(value_w):.0f} W exceeds "
        f"{POWER_BOUND_FACTOR:g} x {what} ({reference_kw:g} kW = {bound_w:.0f} W). "
        "Check the unit of the source entity (kW sent as W?)."
    )
