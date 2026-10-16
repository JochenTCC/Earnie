"""Earnie-Points of one plant (rule: ``docs/spec/earnie-points.md``).

Pure calculation: no I/O, no Streamlit, no network. Invalid input raises ``ValueError``.
"""
from __future__ import annotations

import math

from house_config.consumer_points_fields import APPLIANCE_KIND_AIR_CONDITIONER
from house_config.earnie_role import EARNIE_ROLE_FLEX, resolve_earnie_role
from settings.ev_power import ev_nominal_power_conversion

POINTS_RULE_VERSION = 1

PV_BASE_KWP = 6.0
PV_STEP_KWP = 4.0
STORAGE_BASE_KWH = 5.0
STORAGE_STEP_KWH = 5.0

WALLBOX_POINTS_1_PHASE = 1
WALLBOX_POINTS_3_PHASE = 2
WALLBOX_POINTS_BIDIRECTIONAL = 3
HEAT_POINTS_PER_DEVICE = 1
OTHER_POINTS_PER_DEVICE = 1
OTHER_MIN_NOMINAL_POWER_KW = 2.5

_SUM_DECIMALS = 6


def _tiered_points(total: float, *, base: float, step: float) -> int:
    """0 for no capacity, 1 up to ``base``, then +1 per started ``step``."""
    rounded = round(total, _SUM_DECIMALS)
    if rounded <= 0.0:
        return 0
    if rounded <= base:
        return 1
    return 1 + int(math.ceil(round((rounded - base) / step, _SUM_DECIMALS)))


def _sum_field(items: object, field: str, *, section: str) -> float:
    if not isinstance(items, list):
        raise ValueError(f"earnie_points: components.{section} muss eine Liste sein.")
    total = 0.0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"earnie_points: {section}[{index}] muss ein Objekt sein.")
        name = str(item.get("id") or index)
        if field not in item:
            raise ValueError(f"earnie_points: {section} '{name}': {field} fehlt.")
        try:
            value = float(item[field])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"earnie_points: {section} '{name}': {field} ist keine Zahl ({item[field]!r})."
            ) from exc
        if value < 0.0 or math.isnan(value):
            raise ValueError(f"earnie_points: {section} '{name}': {field} muss >= 0 sein.")
        total += value
    return total


def _pv_points(components: dict) -> int:
    kwp = _sum_field(components.get("pv_systems", []), "kwp", section="pv_systems")
    return _tiered_points(kwp, base=PV_BASE_KWP, step=PV_STEP_KWP)


def _storage_points(components: dict) -> int:
    kwh = _sum_field(
        components.get("batteries", []), "battery_capacity_kwh", section="batteries"
    )
    return _tiered_points(kwh, base=STORAGE_BASE_KWH, step=STORAGE_STEP_KWH)


def _wallbox_consumer_points(consumer: dict) -> int:
    if consumer.get("bidirectional") is True:
        return WALLBOX_POINTS_BIDIRECTIONAL
    _voltage, phases = ev_nominal_power_conversion(consumer)
    if phases == 1:
        return WALLBOX_POINTS_1_PHASE
    if phases == 3:
        return WALLBOX_POINTS_3_PHASE
    raise ValueError(
        f"earnie_points: Wallbox '{consumer.get('id')}': nominal_power_phases={phases} "
        "wird nicht bewertet (erlaubt: 1 oder 3)."
    )


def _is_controlled(consumer: dict) -> bool:
    """Manual / known generic consumers are never counted."""
    if consumer.get("type") == "generic":
        return resolve_earnie_role(consumer) == EARNIE_ROLE_FLEX
    return True


def _is_air_conditioner(consumer: dict) -> bool:
    return consumer.get("appliance_kind") == APPLIANCE_KIND_AIR_CONDITIONER


def _is_large_flex_consumer(consumer: dict) -> bool:
    if consumer.get("type") not in ("generic", "thermal_rc"):
        return False
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    return nominal >= OTHER_MIN_NOMINAL_POWER_KW


def _consumer_parts(consumer: dict) -> dict[str, int]:
    """Points of one consumer; at most one non-zero part (no double counting)."""
    kind = consumer.get("type")
    if kind == "ev":
        return {"wallbox": _wallbox_consumer_points(consumer)}
    if kind == "thermal_annual":
        return {"heat": HEAT_POINTS_PER_DEVICE}
    if not _is_controlled(consumer):
        return {}
    if _is_air_conditioner(consumer):
        return {"heat": HEAT_POINTS_PER_DEVICE}
    if _is_large_flex_consumer(consumer):
        return {"other": OTHER_POINTS_PER_DEVICE}
    return {}


def _consumer_points(profile: dict) -> dict[str, int]:
    consumers = profile.get("consumers")
    if not isinstance(consumers, list):
        raise ValueError("earnie_points: profile.consumers muss eine Liste sein.")
    parts = {"wallbox": 0, "heat": 0, "other": 0}
    for consumer in consumers:
        if not isinstance(consumer, dict):
            raise ValueError("earnie_points: Verbraucher muss ein Objekt sein.")
        for part, points in _consumer_parts(consumer).items():
            parts[part] += points
    return parts


def compute_earnie_points(components: dict, profile: dict) -> dict[str, int]:
    """Earnie-Points of the plant: ``components`` (raw ``components.json`` document)
    and the live house ``profile`` (normalized, with ``consumers``).

    Returns the breakdown plus ``total``; only ``total`` is sent in the usage ping.
    """
    if not isinstance(components, dict):
        raise ValueError("earnie_points: components muss ein Objekt sein.")
    if not isinstance(profile, dict):
        raise ValueError("earnie_points: profile muss ein Objekt sein.")
    parts = {
        "pv": _pv_points(components),
        "storage": _storage_points(components),
        **_consumer_points(profile),
    }
    return {"total": sum(parts.values()), **parts}
