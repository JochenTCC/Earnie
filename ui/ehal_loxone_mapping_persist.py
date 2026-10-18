"""Binding apply/persist helpers for the Loxone EHAL mapping (split from ``ehal_loxone_mapping``).

Names stay importable from ``ui.ehal_loxone_mapping``. Helpers that still live there
(``entity_kind_for_id``, ``_ensure_ehal_loxone_meta``) are resolved at call time.
"""
from __future__ import annotations

import streamlit as st

from house_config.ehal_bindings import ensure_migrated, strip_migrated_config_keys
from integrations.ehal_live import reset_adapter_cache
from ui.ehal_loxone_mapping_base import (
    _SESSION_MIGRATED,
    BATTERY_ENTITY_KIND,
    INVERTER_ENTITY_KIND,
    PLANT_ENTITY_ID,
    PV_ENTITY_KIND,
    _nonempty,
)
from ui.house_config_io import (
    load_house_profiles,
    load_main_config,
    save_house_profiles,
    save_main_config,
)


def _m():
    from ui import ehal_loxone_mapping

    return ehal_loxone_mapping


def apply_entity_bindings(
    house_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write bindings onto plant or consumer; return new doc.

    Battery entities use :func:`apply_battery_bindings` (components.json).
    """
    house = dict(house_doc)
    # Q8: keep keys with empty Merker as activation flags.
    cleaned = {
        str(k): _nonempty(v) for k, v in bindings.items() if str(k or "").strip()
    }
    if entity_id == PLANT_ENTITY_ID:
        plant = dict(house.get("plant") or {}) if isinstance(house.get("plant"), dict) else {}
        plant["ehal_bindings"] = cleaned
        plant.pop("event_triggers", None)
        house["plant"] = plant
        return house
    profiles = house.get("profiles")
    if not isinstance(profiles, dict):
        return house
    profile = dict(profiles.get(profile_id) or {})
    consumers = [dict(c) for c in (profile.get("consumers") or []) if isinstance(c, dict)]
    for consumer in consumers:
        if _nonempty(consumer.get("id")) == entity_id:
            from ehal.flex_fields import canonicalize_consumer_bindings

            ctype = str(consumer.get("type") or "").strip()
            consumer["ehal_bindings"] = canonicalize_consumer_bindings(
                cleaned, entity_id, ctype
            )
            consumer.pop("event_triggers", None)
            break
    profile["consumers"] = consumers
    house["profiles"] = {**profiles, profile_id: profile}
    return house


def apply_battery_bindings(
    components_doc: dict,
    *,
    battery_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write entity-scoped ESS bindings onto ``batteries[].ehal_bindings``.

    Refuses virtual powerstations (no EHAL binding surface).
    """
    from copy import deepcopy

    from house_config.powerstation import is_virtual_powerstation

    out = deepcopy(components_doc) if isinstance(components_doc, dict) else {
        "batteries": [],
        "pv_systems": [],
    }
    batteries = out.get("batteries")
    if not isinstance(batteries, list):
        batteries = []
        out["batteries"] = batteries
    cleaned = {
        str(k): _nonempty(v) for k, v in bindings.items() if str(k or "").strip()
    }
    bid = _nonempty(battery_id)
    found = False
    for index, battery in enumerate(batteries):
        if not isinstance(battery, dict):
            continue
        if _nonempty(battery.get("id")) != bid:
            continue
        if is_virtual_powerstation(battery):
            raise ValueError(
                f"Virtual powerstation '{bid}' has no EHAL bindings "
                "(inherits house ESS; map the house battery instead)."
            )
        updated = dict(battery)
        updated["ehal_bindings"] = cleaned
        batteries[index] = updated
        found = True
        break
    if not found and bid:
        batteries.append({"id": bid, "label": bid, "ehal_bindings": cleaned})
    return out


def apply_inverter_bindings(
    components_doc: dict,
    *,
    inverter_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write entity-scoped inverter bindings onto ``inverters[].ehal_bindings``."""
    from copy import deepcopy

    out = deepcopy(components_doc) if isinstance(components_doc, dict) else {
        "batteries": [],
        "pv_systems": [],
        "inverters": [],
    }
    inverters = out.get("inverters")
    if not isinstance(inverters, list):
        inverters = []
        out["inverters"] = inverters
    cleaned = {
        str(k): _nonempty(v) for k, v in bindings.items() if str(k or "").strip()
    }
    iid = _nonempty(inverter_id)
    found = False
    for index, inverter in enumerate(inverters):
        if not isinstance(inverter, dict):
            continue
        if _nonempty(inverter.get("id")) != iid:
            continue
        updated = dict(inverter)
        updated["ehal_bindings"] = cleaned
        inverters[index] = updated
        found = True
        break
    if not found and iid:
        inverters.append({"id": iid, "label": iid, "ehal_bindings": cleaned})
    return out


def apply_pv_system_bindings(
    components_doc: dict,
    *,
    pv_system_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write entity-scoped PV bindings onto ``pv_systems[].ehal_bindings``."""
    from copy import deepcopy

    out = deepcopy(components_doc) if isinstance(components_doc, dict) else {
        "batteries": [],
        "pv_systems": [],
        "inverters": [],
    }
    systems = out.get("pv_systems")
    if not isinstance(systems, list):
        systems = []
        out["pv_systems"] = systems
    cleaned = {
        str(k): _nonempty(v) for k, v in bindings.items() if str(k or "").strip()
    }
    pid = _nonempty(pv_system_id)
    found = False
    for index, pv in enumerate(systems):
        if not isinstance(pv, dict):
            continue
        if _nonempty(pv.get("id")) != pid:
            continue
        updated = dict(pv)
        updated["ehal_bindings"] = cleaned
        systems[index] = updated
        found = True
        break
    if not found and pid:
        systems.append({"id": pid, "label": pid, "ehal_bindings": cleaned})
    return out


def _migrate_on_open() -> tuple[dict, dict]:
    """Ensure entity bindings exist; persist house + stripped config once when changed."""
    from runtime_store.shadow.mode import is_shadow_config_readonly

    house = load_house_profiles()
    config_doc = load_main_config()
    new_house, new_config, changed = ensure_migrated(house, config_doc)
    if changed and not st.session_state.get(_SESSION_MIGRATED):
        stripped = strip_migrated_config_keys(new_config)
        if is_shadow_config_readonly():
            # Shared Prod config is read-only; keep migrated values in this session only.
            st.session_state[_SESSION_MIGRATED] = True
            return new_house, stripped
        save_house_profiles(new_house)
        save_main_config(stripped)
        reset_adapter_cache()
        st.session_state[_SESSION_MIGRATED] = True
        return new_house, stripped
    return new_house if changed else house, config_doc


def persist_loxone_entity_mapping(
    house: dict,
    config_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    ehal_map: dict[str, str],
    entity_kind: str = "",
) -> str:
    """Persist entity bindings; Shadow → runtime overlay, else house/components + config.

    Returns a short success detail (where data was written).
    """
    from runtime_store.shadow.ehal_overlay import upsert_entity_bindings
    from runtime_store.shadow.mode import is_shadow_config_readonly
    from ui.house_config_io import _load_components_document, _save_components_document

    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    kind = str(entity_kind or "").strip() or _m().entity_kind_for_id(
        migrated_house, profile_id, entity_id
    )
    if is_shadow_config_readonly():
        path = upsert_entity_bindings(
            profile_id=profile_id,
            entity_id=entity_id,
            bindings=ehal_map,
            entity_kind=kind,
        )
        reset_adapter_cache()
        return f"Shadow-Overlay `{path}` (Prod-Config unverändert)"
    if kind == BATTERY_ENTITY_KIND:
        components = apply_battery_bindings(
            _load_components_document(),
            battery_id=entity_id,
            bindings=ehal_map,
        )
        _save_components_document(components)
        save_main_config(_m()._ensure_ehal_loxone_meta(migrated_config))
        reset_adapter_cache()
        return "`components.json` (`batteries[].ehal_bindings`)"
    if kind == INVERTER_ENTITY_KIND:
        components = apply_inverter_bindings(
            _load_components_document(),
            inverter_id=entity_id,
            bindings=ehal_map,
        )
        _save_components_document(components)
        save_main_config(_m()._ensure_ehal_loxone_meta(migrated_config))
        reset_adapter_cache()
        return "`components.json` (`inverters[].ehal_bindings`)"
    if kind == PV_ENTITY_KIND:
        components = apply_pv_system_bindings(
            _load_components_document(),
            pv_system_id=entity_id,
            bindings=ehal_map,
        )
        _save_components_document(components)
        save_main_config(_m()._ensure_ehal_loxone_meta(migrated_config))
        reset_adapter_cache()
        return "`components.json` (`pv_systems[].ehal_bindings`)"
    updated = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=ehal_map,
    )
    save_house_profiles(updated)
    save_main_config(_m()._ensure_ehal_loxone_meta(migrated_config))
    reset_adapter_cache()
    return (
        "`house_profiles.json` (Bindings); Legacy-Merker-Trigger und "
        "Anlagen-Rollen in config bereinigt"
    )
