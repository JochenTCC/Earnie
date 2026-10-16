"""Clear Merker/EFM names from Loxone ``ehal_bindings`` (2.7.q Q8).

Keeps every binding key as an activation flag with an empty string value.
HA entity_id maps are unchanged (caller must only run this for Loxone backends).
"""
from __future__ import annotations

from copy import deepcopy


def clear_binding_values(bindings: dict | None) -> dict[str, str]:
    """``{field: ""}`` for every non-empty key; drop blank keys."""
    if not isinstance(bindings, dict):
        return {}
    return {str(k): "" for k in bindings if str(k or "").strip()}


def _clear_consumers_in_profile(profile: dict) -> dict:
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
    return profile


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
        house["profiles"] = {
            pid: (
                _clear_consumers_in_profile(profile)
                if isinstance(profile, dict)
                else profile
            )
            for pid, profile in profiles.items()
        }
    elif isinstance(profiles, list):
        house["profiles"] = [
            _clear_consumers_in_profile(profile) if isinstance(profile, dict) else profile
            for profile in profiles
        ]
    return house


def clear_loxone_binding_names_in_components(components_doc: dict) -> dict:
    """Return a copy of components.json with empty battery / inverter / PV binding values."""
    doc = deepcopy(components_doc) if isinstance(components_doc, dict) else {}
    for section in ("batteries", "inverters", "pv_systems"):
        entities = doc.get(section)
        if not isinstance(entities, list):
            continue
        out_entities = []
        for entity in entities:
            if not isinstance(entity, dict):
                out_entities.append(entity)
                continue
            entity = dict(entity)
            if isinstance(entity.get("ehal_bindings"), dict):
                entity["ehal_bindings"] = clear_binding_values(entity.get("ehal_bindings"))
            out_entities.append(entity)
        doc[section] = out_entities
    return doc
