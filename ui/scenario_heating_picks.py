"""Scenario editor: heating-system variant per thermal_annual consumer (heating_system_ids).

One select box per ``thermal_annual`` consumer of the selected house profile. The reference
system (installed, used by Live and for the baseload) is the default; a pick equal to it is
not stored. The Live scenario always uses the reference system (no select box).
"""
from __future__ import annotations

import streamlit as st

from house_config.heating_systems import HEATING_SYSTEM_ID_KEY
from ui.scenario_form_helpers import (
    lookup_entity_id,
    options_for_entities,
    render_entity_selectbox,
    scoped_widget_key,
    seed_entity_select_state,
)

_KEY_PREFIX = "scenario_heating_"


def list_heating_systems() -> list[dict]:
    from house_config.components_store import load_components_document
    from house_config.heating_systems import normalize_heating_systems
    from runtime_store.persist_paths import resolve_components_json_path

    doc = load_components_document(resolve_components_json_path())
    return normalize_heating_systems(doc.get("heating_systems"))


def thermal_consumers(profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in (profile or {}).get("consumers") or []
        if consumer.get("type") == "thermal_annual" and consumer.get(HEATING_SYSTEM_ID_KEY)
    ]


def _widget_base(consumer_id: str) -> str:
    return f"{_KEY_PREFIX}{consumer_id}"


def _choices(catalog: list[dict], reference_id: str) -> list[dict]:
    """Catalog entries; the reference system is marked in its label."""
    out: list[dict] = []
    for entry in catalog:
        label = str(entry.get("label") or entry["id"])
        if entry["id"] == reference_id:
            label = f"{label} (Referenzsystem)"
        out.append({"id": entry["id"], "label": label})
    return out


def seed_heating_picks(session_scope: str, settings: dict, profiles: dict[str, dict]) -> None:
    profile = profiles.get(str(settings.get("house_profile_id") or "").strip()) or {}
    consumers = thermal_consumers(profile)
    if not consumers:
        return
    catalog = list_heating_systems()
    picks = settings.get("heating_system_ids") or {}
    for consumer in consumers:
        cid = str(consumer["id"])
        reference_id = consumer[HEATING_SYSTEM_ID_KEY]
        seed_entity_select_state(
            session_scope,
            _widget_base(cid),
            _choices(catalog, reference_id),
            str(picks.get(cid) or reference_id),
        )


def render_heating_picks(
    session_scope: str,
    profile: dict,
    *,
    is_live: bool,
) -> dict[str, str]:
    """Select boxes; returns only picks that differ from the reference system."""
    consumers = thermal_consumers(profile)
    if not consumers:
        return {}
    if is_live:
        st.caption(
            "Heizsystem: Das Live-Szenario rechnet immer mit dem Referenzsystem aus dem "
            "Hauskonfigurator. Varianten in einem eigenen Szenario wählen."
        )
        return {}
    catalog = list_heating_systems()
    picks: dict[str, str] = {}
    for consumer in consumers:
        cid = str(consumer["id"])
        reference_id = consumer[HEATING_SYSTEM_ID_KEY]
        items = _choices(catalog, reference_id)
        key = scoped_widget_key(session_scope, _widget_base(cid))
        _labels, mapping = options_for_entities(items)
        if st.session_state.get(key) not in mapping:
            seed_entity_select_state(session_scope, _widget_base(cid), items, reference_id)
        pick = render_entity_selectbox(
            f"Heizsystem ({consumer.get('label') or cid})",
            items,
            key=key,
        )
        system_id = lookup_entity_id(mapping, pick)
        if system_id and system_id != reference_id:
            picks[cid] = system_id
    st.caption(
        "Die Grundlast rechnet immer mit dem Referenzsystem; die Variante tauscht nur die "
        "Wärmeerzeugung. Varianten im Abschnitt „Heizsystem-Varianten“ anlegen."
    )
    return picks
