"""Shadow-only EHAL bindings overlay under ``EARNIE_RUNTIME_PATH``.

Prod ``house_profiles.json`` stays read-only. Mapping UI saves land here and
``load_house_profiles_document`` merges them when ``EARNIE_SHADOW=1``.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

OVERLAY_FILENAME = "shadow_ehal_bindings.json"
PLANT_ENTITY_ID = "plant"


def overlay_path() -> str:
    from runtime_store.persist_paths import runtime_path

    return runtime_path(OVERLAY_FILENAME)


def read_overlay() -> dict[str, Any]:
    path = overlay_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_overlay(doc: dict[str, Any]) -> str:
    from runtime_store.data_model import stamp_data_model

    path = overlay_path()
    payload = dict(doc)
    stamp_data_model(payload)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def _clean_bindings(bindings: dict[str, str]) -> dict[str, str]:
    return {
        str(key): str(value).strip()
        for key, value in bindings.items()
        if str(value).strip()
    }


def upsert_entity_bindings(
    *,
    profile_id: str,
    entity_id: str,
    bindings: dict[str, str],
) -> str:
    """Replace one entity's bindings in the overlay; return absolute path."""
    cleaned = _clean_bindings(bindings)
    doc = read_overlay()
    eid = str(entity_id or "").strip()
    if eid == PLANT_ENTITY_ID:
        doc["plant_bindings"] = cleaned
    else:
        by_profile = dict(doc.get("consumer_bindings") or {})
        profile_map = dict(by_profile.get(profile_id) or {})
        profile_map[eid] = cleaned
        by_profile[str(profile_id)] = profile_map
        doc["consumer_bindings"] = by_profile
    return write_overlay(doc)


def apply_overlay_to_house(house: dict) -> dict:
    """Return house with overlay bindings applied (deep copy when overlay present)."""
    overlay = read_overlay()
    if not overlay:
        return house
    plant_b = overlay.get("plant_bindings")
    by_profile = overlay.get("consumer_bindings")
    if not isinstance(plant_b, dict) and not isinstance(by_profile, dict):
        return house
    out = deepcopy(house)
    if isinstance(plant_b, dict):
        plant = dict(out.get("plant") or {}) if isinstance(out.get("plant"), dict) else {}
        plant["ehal_bindings"] = _clean_bindings(
            {str(k): str(v) for k, v in plant_b.items()}
        )
        out["plant"] = plant
    if isinstance(by_profile, dict):
        _apply_consumer_overlay(out, by_profile)
    return out


def _apply_consumer_overlay(house: dict, by_profile: dict) -> None:
    profiles = house.get("profiles")
    if not isinstance(profiles, dict):
        return
    new_profiles = dict(profiles)
    for pid, consumers_map in by_profile.items():
        if not isinstance(consumers_map, dict):
            continue
        profile = dict(new_profiles.get(pid) or {})
        consumers = [
            dict(c) for c in (profile.get("consumers") or []) if isinstance(c, dict)
        ]
        for consumer in consumers:
            cid = str(consumer.get("id") or "").strip()
            raw = consumers_map.get(cid)
            if isinstance(raw, dict):
                consumer["ehal_bindings"] = _clean_bindings(
                    {str(k): str(v) for k, v in raw.items()}
                )
        profile["consumers"] = consumers
        new_profiles[str(pid)] = profile
    house["profiles"] = new_profiles


def clear_overlay() -> None:
    path = overlay_path()
    if os.path.isfile(path):
        os.remove(path)
