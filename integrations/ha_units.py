"""Physical quantity of EHAL fields and HA unit conversion (no HA libraries).

Two rules for HA mapping:

1. Only physically compatible signals are bound: an EHAL power field accepts
   W / kW / MW, never kWh or %.
2. The conversion factor is derived from the entity's ``unit_of_measurement``
   at runtime (read *and* write), never stored with the binding — a unit change
   in HA is picked up on the next read/write.

EHAL base units: power W, energy kWh, percent %, current A.
"""
from __future__ import annotations

import math
from typing import Literal

# Quantity → {normalized unit → factor to the EHAL base unit}.
QUANTITY_UNITS: dict[str, dict[str, float]] = {
    "power": {"w": 1.0, "kw": 1000.0, "mw": 1_000_000.0},
    "energy": {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0},
    "percent": {"%": 1.0},
    "current": {"a": 1.0, "ma": 0.001},
}

QUANTITY_BASE_UNIT = {"power": "W", "energy": "kWh", "percent": "%", "current": "A"}

_UNIT_ALIASES = {
    "watt": "w",
    "watts": "w",
    "kilowatt": "kw",
    "kilowatts": "kw",
    "megawatt": "mw",
    "megawatts": "mw",
    "watt-hour": "wh",
    "watt-hours": "wh",
    "watthour": "wh",
    "watthours": "wh",
    "kilowatt-hour": "kwh",
    "kilowatt-hours": "kwh",
    "megawatt-hour": "mwh",
    "megawatt-hours": "mwh",
    "percent": "%",
    "amp": "a",
    "amps": "a",
    "ampere": "a",
    "milliampere": "ma",
}

# HA device_class → quantity (a conflicting device_class also rules an entity out).
DEVICE_CLASS_QUANTITY = {
    "power": "power",
    "energy": "energy",
    "battery": "percent",
    "current": "current",
}

# EHAL field → quantity. Fields not listed (modes, flags, temperatures, …) are
# unconstrained here.
FIELD_QUANTITY: dict[str, str] = {
    "sens_grid_power_active": "power",
    "sens_pv_production_active": "power",
    "sens_ess_power": "power",
    "sens_evcs_active_power": "power",
    "sens_power_consumers": "power",
    "flex.sens_power_act": "power",
    "sens_pv_energy": "energy",
    "sens_grid_energy_import": "energy",
    "sens_grid_energy_export": "energy",
    "sens_evcs_bat_capacity": "energy",
    "sens_ess_soc": "percent",
    "sens_evcs_soc_act": "percent",
    "get_evcs_limit_soc": "percent",
    "get_evcs_soc_min_immediate": "percent",
    "set_ess_active_power": "power",
    "set_ess_charge_power_limit": "power",
    "set_ess_discharge_power_limit": "power",
    "set_evcs_max_current": "current",
    "get_evcs_nominal_current": "current",
}

UnitCheck = Literal["ok", "unknown", "mismatch", "free"]


class UnitMismatchError(ValueError):
    """HA entity unit belongs to another physical quantity than the EHAL field."""


def normalize_unit(unit: object) -> str:
    text = str(unit or "").strip().lower()
    return _UNIT_ALIASES.get(text, text)


def unit_quantity(unit: object) -> str | None:
    """Quantity a unit belongs to (``None`` for empty or unknown units)."""
    key = normalize_unit(unit)
    for quantity, factors in QUANTITY_UNITS.items():
        if key in factors:
            return quantity
    return None


def field_quantity(field: str) -> str | None:
    return FIELD_QUANTITY.get(str(field))


def unit_check(field: str, unit: object, *, device_class: object = None) -> UnitCheck:
    """Rule 1: is an entity with ``unit`` (and ``device_class``) bindable to ``field``?

    ``free``     field has no physical quantity (mode, flag, …)
    ``ok``       unit belongs to the field's quantity
    ``unknown``  entity has no unit and no conflicting device_class
    ``mismatch`` unit or device_class belongs to another quantity (any unit
                 outside the field's quantity counts, e.g. kWh, %, °C, VA)
    """
    quantity = field_quantity(field)
    if quantity is None:
        return "free"
    dc_quantity = DEVICE_CLASS_QUANTITY.get(str(device_class or "").strip().lower())
    if dc_quantity is not None and dc_quantity != quantity:
        return "mismatch"
    key = normalize_unit(unit)
    if not key:
        return "unknown"
    if key in QUANTITY_UNITS[quantity]:
        return "ok"
    # Any other unit (kWh, %, °C, VA, …) is a different physical signal.
    return "mismatch"


def unit_factor(field: str, unit: object) -> float:
    """Rule 2: factor entity unit → EHAL base unit (1.0 if free/unknown).

    Raises :class:`UnitMismatchError` if the unit belongs to another quantity.
    """
    quantity = field_quantity(field)
    if quantity is None:
        return 1.0
    key = normalize_unit(unit)
    if not key:
        return 1.0
    factors = QUANTITY_UNITS[quantity]
    if key not in factors:
        raise UnitMismatchError(
            f"{field} needs {quantity} ({QUANTITY_BASE_UNIT[quantity]}), "
            f"entity unit is {unit!r}"
        )
    return factors[key]


def to_ehal(field: str, value: float, unit: object) -> float:
    """HA value in entity unit → EHAL base unit."""
    return float(value) * unit_factor(field, unit)


def from_ehal(field: str, value: float, unit: object) -> float:
    """EHAL base-unit value → entity unit (for setpoint writes)."""
    return float(value) / unit_factor(field, unit)


def describe_conversion(field: str, unit: object) -> str:
    """Short UI hint, e.g. ``kW → W (×1000)``; empty when no conversion applies."""
    quantity = field_quantity(field)
    if quantity is None or not normalize_unit(unit):
        return ""
    try:
        factor = unit_factor(field, unit)
    except UnitMismatchError:
        return ""
    if math.isclose(factor, 1.0, rel_tol=0.0, abs_tol=1e-12):
        return ""
    return f"{unit} → {QUANTITY_BASE_UNIT[quantity]} (×{factor:g})"
