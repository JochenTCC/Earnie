"""Clear Merker/EFM names from Loxone ``ehal_bindings`` (2.7.q Q8).

Keeps every binding key as an activation flag with an empty string value.
HA entity_id maps are unchanged (caller must only run this for Loxone backends).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def clear_binding_values(bindings: dict | None) -> dict[str, str]:
    """``{field: ""}`` for every non-empty key; drop blank keys."""
    if not isinstance(bindings, dict):
        return {}
    return {str(k): "" for k in bindings if str(k or "").strip()}


def clear_loxone_binding_names_in_house(house_doc: dict) -> dict:
    """Return a copy of house_profiles with empty plant/consumer binding values."""
    house = deepcopy(house_doc) if isinstance(house_doc, dict) else {}
    plant = house.get("plant")
    if isinstance(plant, dict) and isinstance(plant.get("ehal_bindings"), dict):
        plant = dict(plant)
        plant["ehal_bindings"] = clear_binding_values(plant.get("ehal_bindings"))
        house["plant"] = plant
    profiles = house.get("profiles")
    if isinstance(profiles, dict):
        new_profiles: dict[str, Any] = {}
        for pid, profile in profiles.items():
            if not isinstance(profile, dict):
                new_profiles[pid] = profile
                continue
            profile = dict(profile)
            consumers = []
            for consumer in profile.get("consumers") or []:
                if not isinstance(consumer, dict):
                    consumers.append(consumer)
                    continue
                consumer = dict(consumer)
                if isinstance(consumer.get("ehal_bindings"), dict):
                    consumer["ehal_bindings"] = clear_binding_values(
                        consumer.get("ehal_bindings")
                    )
                consumers.append(consumer)
            profile["consumers"] = consumers
            new_profiles[pid] = profile
        house["profiles"] = new_profiles
    return house


def clear_loxone_binding_names_in_components(components_doc: dict) -> dict:
    """Return a copy of components.json with empty battery binding values."""
    doc = deepcopy(components_doc) if isinstance(components_doc, dict) else {}
    batteries = doc.get("batteries")
    if not isinstance(batteries, list):
        return doc
    out_batteries = []
    for battery in batteries:
        if not isinstance(battery, dict):
            out_batteries.append(battery)
            continue
        battery = dict(battery)
        if isinstance(battery.get("ehal_bindings"), dict):
            battery["ehal_bindings"] = clear_binding_values(battery.get("ehal_bindings"))
        out_batteries.append(battery)
    doc["batteries"] = out_batteries
    return doc
