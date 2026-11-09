"""Earnie-Points of one plant (rule: ``docs/workflow/earnie-points.md``).

Pure calculation: no I/O, no Streamlit, no network. Invalid input raises ``ValueError``.
"""
from __future__ import annotations

import math

from house_config.earnie_role import EARNIE_ROLE_FLEX, resolve_earnie_role
from house_config.heat_source import consumer_heat_source, heating_rod_part

POINTS_RULE_VERSION = 2

PV_KWP_PER_POINT = 7.0
STORAGE_KINK_KWH_PER_KWP = 1.0
STORAGE_KWH_PER_POINT_BELOW_KINK = 5.0
STORAGE_KWH_PER_POINT_ABOVE_KINK = 2.5
EV_STORAGE_WEIGHT = 0.25
EV_STORAGE_MIN_POINTS = 1

WALLBOX_POINTS = 2
WALLBOX_NO_STORAGE_EXTRA = 4
WALLBOX_NO_STORAGE_BELOW_KWH = 1.0

HEAT_PUMP_POINTS = 1
HEATING_ROD_BASE_POINTS: dict[str, int] = {
    "gas": 7,
    "oil": 7,
    "district_heat": 7,
    "pellets": 4,
    "wood": 4,
    "electric_direct": 0,
    "heat_pump": 0,
}
HEATING_ROD_KWP_PER_DEDUCTION = 5.0

OTHER_POINTS_PER_DEVICE = 1
OTHER_MIN_NOMINAL_POWER_KW = 2.5

_SUM_DECIMALS = 6


def _half_up(value: float) -> int:
    """Round to whole points, 0.5 rounds up (kaufmännisch); float noise ignored."""
    return int(math.floor(round(value, _SUM_DECIMALS) + 0.5))


def _number(item: dict, field: str, *, section: str, name: str) -> float:
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
    return value


def _sum_field(items: object, field: str, *, section: str) -> float:
    if not isinstance(items, list):
        raise ValueError(f"earnie_points: components.{section} muss eine Liste sein.")
    total = 0.0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"earnie_points: {section}[{index}] muss ein Objekt sein.")
        total += _number(item, field, section=section, name=str(item.get("id") or index))
    return total


def _storage_points(kwh: float, kwp: float) -> int:
    """Up to 1 kWh per kWp: 1 point per 5 kWh; above: 1 point per 2.5 kWh."""
    kink = kwp * STORAGE_KINK_KWH_PER_KWP
    low, high = min(kwh, kink), max(0.0, kwh - kink)
    return _half_up(
        low / STORAGE_KWH_PER_POINT_BELOW_KINK + high / STORAGE_KWH_PER_POINT_ABOVE_KINK
    )


def _is_controlled(consumer: dict) -> bool:
    """Manual / known generic consumers are never counted."""
    if consumer.get("type") == "generic":
        return resolve_earnie_role(consumer) == EARNIE_ROLE_FLEX
    return True


def _is_large_flex_consumer(consumer: dict) -> bool:
    if consumer.get("type") not in ("generic", "thermal_rc"):
        return False
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    return nominal >= OTHER_MIN_NOMINAL_POWER_KW


def _ev_storage_kwh(consumer: dict) -> float:
    """Car battery of a bidirectional wallbox, weighted a quarter of a stationary storage."""
    if consumer.get("bidirectional") is not True:
        return 0.0
    name = str(consumer.get("id") or "?")
    return EV_STORAGE_WEIGHT * _number(
        consumer, "battery_capacity_kwh", section="Wallbox", name=name
    )


def _heating_rod_points(consumer: dict, kwp: float) -> int:
    """Rod points by the heat source it backs up, minus 1 per 5 kWp of PV, at least 0."""
    if heating_rod_part(consumer) is None:
        return 0
    source_type = consumer_heat_source(consumer)["type"]
    if source_type not in HEATING_ROD_BASE_POINTS:
        raise ValueError(
            f"earnie_points: Heizstab an '{consumer.get('id')}': Wärmequelle "
            f"'{source_type}' wird nicht bewertet."
        )
    base = HEATING_ROD_BASE_POINTS[source_type]
    return max(0, _half_up(base - kwp / HEATING_ROD_KWP_PER_DEDUCTION))


def _cooling_points(profile: dict) -> int:
    """Air conditioning („Kühlung betrachten“): a split device counts 1 heat point; a reversible
    heat pump only when its heating is not counted already (switch „Heizung betrachten“ off)."""
    from house_config.house_cooling import COOLING_KEY, COOLING_TYPE_SPLIT, cooling_consumer

    carrier = cooling_consumer(profile)
    if carrier is None:
        return 0
    if carrier[COOLING_KEY]["type"] == COOLING_TYPE_SPLIT:
        return HEAT_PUMP_POINTS
    heating_counted = any(c is carrier for c in profile.get("consumers") or [])
    return 0 if heating_counted else HEAT_PUMP_POINTS


def _consumers(profile: dict) -> list[dict]:
    consumers = profile.get("consumers")
    if not isinstance(consumers, list):
        raise ValueError("earnie_points: profile.consumers muss eine Liste sein.")
    for consumer in consumers:
        if not isinstance(consumer, dict):
            raise ValueError("earnie_points: Verbraucher muss ein Objekt sein.")
    return consumers


def compute_earnie_points(components: dict, profile: dict) -> dict[str, int]:
    """Earnie-Points of the plant: ``components`` (raw ``components.json`` document)
    and the live house ``profile`` (normalized, with ``consumers``).

    Returns the breakdown plus ``total``; only ``total`` is sent in the usage ping.
    Each consumer contributes to one part only (no double counting). The car battery of a
    bidirectional wallbox adds to ``wallbox``: the storage points it would add at a quarter of
    its capacity, at least 1 point per bidirectional wallbox.
    """
    if not isinstance(components, dict):
        raise ValueError("earnie_points: components muss ein Objekt sein.")
    if not isinstance(profile, dict):
        raise ValueError("earnie_points: profile muss ein Objekt sein.")
    kwp = _sum_field(components.get("pv_systems", []), "kwp", section="pv_systems")
    stationary_kwh = _sum_field(
        components.get("batteries", []), "battery_capacity_kwh", section="batteries"
    )
    bidirectional = heat = rod = other = 0
    wallbox_ids: set[str] = set()
    ev_kwh = 0.0
    for consumer in _consumers(profile):
        kind = consumer.get("type")
        if kind == "ev":
            # A wallbox counts once, however many cars it serves (data model 6).
            wallbox_ids.add(str(consumer["wallbox_assignment"]["wallbox_id"]))
            if consumer.get("bidirectional") is True:
                bidirectional += 1
                ev_kwh += _ev_storage_kwh(consumer)
        elif kind == "thermal_annual":
            if consumer_heat_source(consumer)["type"] == "heat_pump":
                heat += HEAT_PUMP_POINTS
            rod += _heating_rod_points(consumer, kwp)
        elif _is_controlled(consumer) and _is_large_flex_consumer(consumer):
            other += OTHER_POINTS_PER_DEVICE
    wallboxes = len(wallbox_ids)
    wallbox = WALLBOX_POINTS * wallboxes
    if wallboxes and stationary_kwh < WALLBOX_NO_STORAGE_BELOW_KWH:
        wallbox += WALLBOX_NO_STORAGE_EXTRA
    storage = _storage_points(stationary_kwh, kwp)
    if bidirectional:
        ev_delta = _storage_points(stationary_kwh + ev_kwh, kwp) - storage
        wallbox += max(EV_STORAGE_MIN_POINTS * bidirectional, ev_delta)
    parts = {
        "pv": _half_up(kwp / PV_KWP_PER_POINT),
        "storage": storage,
        "wallbox": wallbox,
        "heat": heat + _cooling_points(profile),
        "heating_rod": rod,
        "other": other,
    }
    return {"total": sum(parts.values()), **parts}
