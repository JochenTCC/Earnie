"""SUSI P6: household-electricity reference values per household size (plausibility only).

SUSI reference values (tooltip of the SUSI planning calculator, Energieinstitut Vorarlberg):
1 person 1,700, 2 persons 3,400, 3 persons 4,200, 4 or more persons 4,700 kWh/a, **without**
the electricity of a heat generator. Earnie's ``annual_kwh`` holds the whole house, so the
comparison takes ``annual_kwh`` minus the modeled large consumers that are not ordinary
household electricity: heating (``thermal_annual``), EV and pool / RC store (``thermal_rc``,
decided 2026-11-03). Appliance consumers (``generic``) are household electricity and stay in.
The heating rod has no annual consumption of its own (it stays out of the demand).
A deviation above ±40 % shows a warning; it never blocks saving.
"""
from __future__ import annotations

from house_config.baseload import consumer_annual_kwh

_REFERENCE_KWH_BY_PERSONS: dict[int, float] = {1: 1700.0, 2: 3400.0, 3: 4200.0, 4: 4700.0}
_MAX_LISTED_PERSONS = max(_REFERENCE_KWH_BY_PERSONS)
DEVIATION_WARN_FRACTION = 0.40
NON_HOUSEHOLD_CONSUMER_TYPES: tuple[str, ...] = ("thermal_annual", "ev", "thermal_rc")


def household_reference_kwh(persons: int) -> float:
    """SUSI reference value (kWh/a) for ``persons`` (4 or more share the 4-person value)."""
    count = int(persons)
    if count < 1:
        raise ValueError(f"persons muss >= 1 sein (ist {count}).")
    return _REFERENCE_KWH_BY_PERSONS[min(count, _MAX_LISTED_PERSONS)]


def household_comparison(
    annual_kwh: float, persons: int, consumers: list[dict], *, cooling_kwh: float = 0.0
) -> dict:
    """Household electricity of the profile vs. the SUSI reference value.

    ``consumers`` are the planned consumers of the profile (preview shape, as for the
    baseload); ``cooling_kwh`` the air conditioning („Kühlung betrachten“), excluded like the
    heating. Returns ``reference_kwh``, ``excluded_kwh`` (Σ heating, EV, pool, cooling),
    ``excluded_labels``, ``household_kwh`` (``annual_kwh`` − excluded, may be negative when
    the consumers over-allocate), ``deviation`` (fraction vs. the reference) and ``warn``.
    """
    reference = household_reference_kwh(persons)
    excluded = [c for c in consumers if c.get("type") in NON_HOUSEHOLD_CONSUMER_TYPES]
    excluded_kwh = sum(float(consumer_annual_kwh(c)) for c in excluded) + float(cooling_kwh)
    labels = [str(c.get("label") or c.get("name") or c.get("id")) for c in excluded]
    if cooling_kwh > 0.0:
        labels.append("Klimaanlage")
    household = float(annual_kwh) - excluded_kwh
    deviation = (household - reference) / reference
    return {
        "reference_kwh": reference,
        "excluded_kwh": round(excluded_kwh, 3),
        "excluded_labels": labels,
        "household_kwh": round(household, 3),
        "deviation": deviation,
        "warn": abs(deviation) > DEVIATION_WARN_FRACTION,
    }
