"""Scenario editor: heating-system variant per thermal_annual consumer (heating_system_ids).

One select box per ``thermal_annual`` consumer of the selected house profile. Its choices are
the house's own reference system (installed, used by Live and for the baseload; default, a pick
equal to it is not stored) and the variants (entries that are no house's reference system).
The Live scenario (Ist- / Referenz-Szenario) always uses the reference system: a text line,
no select box.
"""
from __future__ import annotations

import streamlit as st

from house_config.heating_systems import HEATING_SYSTEM_ID_KEY, scenario_heating_choices
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


def _house_raw() -> dict:
    from house_config.heating_systems import read_raw_json
    from runtime_store.persist_paths import resolve_house_profiles_json_path

    return read_raw_json(resolve_house_profiles_json_path())


def _choices(
    catalog: list[dict], house_raw: dict, profile_id: str, consumer: dict
) -> list[dict]:
    """Own reference system (marked in its label) first, then the variants."""
    by_id = {entry["id"]: entry for entry in catalog}
    reference_id = consumer[HEATING_SYSTEM_ID_KEY]
    ids = scenario_heating_choices(
        by_id,
        house_doc=house_raw,
        profile_id=profile_id,
        consumer_id=str(consumer["id"]),
    )
    out: list[dict] = []
    for system_id in ids:
        entry = by_id.get(system_id)
        if entry is None:
            continue
        label = str(entry.get("label") or entry["id"])
        if entry["id"] == reference_id:
            label = f"{label} (Referenzsystem)"
        out.append({"id": entry["id"], "label": label})
    return out


def _reference_label(catalog: list[dict], reference_id: str) -> str:
    entry = next((item for item in catalog if item["id"] == reference_id), None)
    return str((entry or {}).get("label") or reference_id)


def seed_heating_picks(session_scope: str, settings: dict, profiles: dict[str, dict]) -> None:
    profile = profiles.get(str(settings.get("house_profile_id") or "").strip()) or {}
    consumers = thermal_consumers(profile)
    if not consumers:
        return
    catalog = list_heating_systems()
    house_raw = _house_raw()
    profile_id = str(profile.get("id") or "")
    picks = settings.get("heating_system_ids") or {}
    for consumer in consumers:
        cid = str(consumer["id"])
        reference_id = consumer[HEATING_SYSTEM_ID_KEY]
        seed_entity_select_state(
            session_scope,
            _widget_base(cid),
            _choices(catalog, house_raw, profile_id, consumer),
            str(picks.get(cid) or reference_id),
        )


def heating_picks_from_session(session_state, session_scope: str, profile: dict) -> dict[str, str]:
    """The form's picks as stored in ``settings.heating_system_ids`` (unsaved-edit check).

    Same rule as ``render_heating_picks``: only picks that differ from the reference system.
    A select box not seeded yet shows the reference system, so it adds no pick.
    """
    consumers = thermal_consumers(profile)
    if not consumers:
        return {}
    catalog = list_heating_systems()
    house_raw = _house_raw()
    profile_id = str(profile.get("id") or "")
    picks: dict[str, str] = {}
    for consumer in consumers:
        cid = str(consumer["id"])
        reference_id = consumer[HEATING_SYSTEM_ID_KEY]
        _labels, mapping = options_for_entities(
            _choices(catalog, house_raw, profile_id, consumer)
        )
        system_id = lookup_entity_id(
            mapping, session_state.get(scoped_widget_key(session_scope, _widget_base(cid)))
        )
        if system_id and system_id != reference_id:
            picks[cid] = system_id
    return picks


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
    catalog = list_heating_systems()
    if is_live:
        for consumer in consumers:
            label = _reference_label(catalog, consumer[HEATING_SYSTEM_ID_KEY])
            st.markdown(
                f"Heizsystem: {label} (Referenzsystem, Änderung im Hauskonfigurator)"
            )
        st.caption("Varianten in einem weiteren Szenario wählen.")
        return {}
    house_raw = _house_raw()
    profile_id = str(profile.get("id") or "")
    picks: dict[str, str] = {}
    for consumer in consumers:
        cid = str(consumer["id"])
        reference_id = consumer[HEATING_SYSTEM_ID_KEY]
        items = _choices(catalog, house_raw, profile_id, consumer)
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
        "Wärmeerzeugung. Varianten im Hauskonfigurator im Bereich „Heizsysteme“ anlegen."
    )
    return picks
