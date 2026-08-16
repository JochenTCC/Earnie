"""Entity-centric Loxone → EHAL HITL mapping UI (2.4.k)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from house_config.ehal_bindings import (
    FILTER_EHAL_FIELDS,
    THERMAL_RC_EHAL_FIELDS,
    ensure_migrated,
    filter_ehal_fields_for_consumer,
    strip_migrated_config_keys,
)
from integrations.ehal_live import reset_adapter_cache
from integrations.loxone_ehal_mapping import (
    FIELD_LABELS,
    SETPOINT_FIELDS,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
    heuristic_propose,
)
from integrations.loxone_greenfield_import import probe_marker_names
from integrations.loxone_structure import (
    SOURCE_HTTP_PROBE,
    scan_structure,
)
from ui.house_config_io import (
    get_live_scenario_refs,
    load_house_profiles,
    load_main_config,
    save_house_profiles,
    save_main_config,
)

_NONE = "— nicht gemappt —"
_SESSION_SCAN = "ehal_lox_scan"
_SESSION_PROPOSALS = "ehal_lox_proposals"
_SESSION_ENTITY = "ehal_lox_entity_id"
_SESSION_MIGRATED = "ehal_lox_migrated_once"
_SESSION_MANUAL_NAMES = "ehal_lox_manual_names"
_SESSION_MANUAL_FEEDBACK = "ehal_lox_manual_feedback"
_SESSION_PENDING_NEW = "ehal_lox_pending_new_marker"

PLANT_ENTITY_ID = "plant"

PLANT_FIELDS: tuple[str, ...] = (
    TELEMETRY_REQUIRED
    + tuple(f for f in TELEMETRY_OPTIONAL if f != "sens_evcs_active_power")
    + tuple(
        f
        for f in SETPOINT_FIELDS
        if f.startswith("set_ess_")
    )
)

EV_FIELDS: tuple[str, ...] = (
    "sens_evcs_active_power",
    "sens_evcs_connected",
    "sens_evcs_soc_act",
    "get_evcs_nominal_current",
    "sens_evcs_bat_capacity",
    "get_evcs_ready_by_time",
    "get_evcs_limit_soc",
    "get_evcs_soc_min_immediate",
    "set_evcs_max_current",
    "set_evcs_mode",
)

FLEX_FIELDS: tuple[str, ...] = (
    "flex.sens_power_act",
    "flex.set_enable",
    "flex.set_power_setpoint",
)

FILTER_FIELDS: tuple[str, ...] = FILTER_EHAL_FIELDS

_EXTRA_LABELS: dict[str, str] = {
    "sens_evcs_connected": "EV angeschlossen",
    "sens_evcs_soc_act": "EV Ist-SOC (%)",
    "get_evcs_nominal_current": "EV Nennstrom (A)",
    "sens_evcs_bat_capacity": "EV Batteriekapazität (kWh)",
    "get_evcs_ready_by_time": "EV FertigUm",
    "get_evcs_limit_soc": "EV Ladeziel-SOC (%)",
    "get_evcs_soc_min_immediate": "EV SOC-Min Sofort (%)",
    "flex.power_name": "Flex Leistung / Zustand",
    "flex.enable_name": "Flex Freigabe",
    "flex.power_setpoint_name": "Flex Leistungs-Sollwert",
    "flex.sens_power_act": "Flex Leistung / Zustand",
    "flex.set_enable": "Flex Freigabe",
    "flex.set_power_setpoint": "Flex Leistungs-Sollwert",
    "get_filter_remaining_hours": "Filter Sollstunden (h)",
    "sens_filter_active": "Filter läuft (Binär)",
    "get_filter_native_start_hour": "Native Filter-Startstunde",
    "get_filter_native_duration_hours": "Native Filter-Dauer (h)",
    "sens_temperature_water": "Pool Ist-Temperatur (°C)",
    "get_temperature_water_setpoint": "Pool Soll-Temperatur (°C)",
    "get_temperature_tolerance_c": "Temperatur-Toleranz (°C)",
    "sens_heating_active": "Heizung aktiv",
    "sens_temperature_outside": "Außentemperatur (°C)",
}


def _field_label(field: str) -> str:
    from ehal.flex_fields import flex_field_label

    labels = {**role_field_labels(), **FIELD_LABELS, **_EXTRA_LABELS}
    pattern_label = flex_field_label(field)
    if pattern_label:
        return pattern_label
    return labels.get(field, field)


def _field_select_caption(
    field: str,
    *,
    required: bool = False,
) -> str:
    """Bedeutung + EHAL value name for HITL select labels."""
    meaning = _field_label(field)
    suffix = " *" if required else ""
    return f"{meaning} (`{field}`){suffix}"


def _nonempty(value: object) -> str:
    return str(value or "").strip()


def fields_for_consumer(consumer: dict) -> tuple[str, ...]:
    """EHAL mapping fields for a house-profile consumer type."""
    if str(consumer.get("type") or "") == "ev":
        return EV_FIELDS
    from ehal.flex_fields import flex_fields_for_consumer

    cid = str(consumer.get("id") or "").strip()
    if cid == "pool_filter":
        return filter_ehal_fields_for_consumer("pool_filter")
    if cid:
        base = flex_fields_for_consumer(cid)
    else:
        base = FLEX_FIELDS
    if str(consumer.get("type") or "") == "thermal_rc":
        return base + THERMAL_RC_EHAL_FIELDS
    return base


def binding_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): _nonempty(v) for k, v in raw.items() if _nonempty(v)}


def resolve_live_profile_id(house_doc: dict) -> str:
    """Prefer Live-Szenario house_profile_id; else first profile id."""
    refs = get_live_scenario_refs()
    profile_id = _nonempty(refs.get("house_profile_id"))
    profiles = house_doc.get("profiles") or {}
    if isinstance(profiles, dict):
        if profile_id and profile_id in profiles:
            return profile_id
        return next(iter(profiles), "")
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict) and _nonempty(profile.get("id")) == profile_id:
                return profile_id
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("id"):
                return str(profile["id"])
    return ""


def consumers_for_profile(house_doc: dict, profile_id: str) -> list[dict]:
    profiles = house_doc.get("profiles") or {}
    if isinstance(profiles, dict):
        profile = profiles.get(profile_id) if profile_id else None
    elif isinstance(profiles, list):
        profile = next(
            (
                p
                for p in profiles
                if isinstance(p, dict) and str(p.get("id") or "") == profile_id
            ),
            None,
        )
    else:
        profile = None
    if not isinstance(profile, dict):
        return []
    raw = profile.get("consumers") or []
    return [c for c in raw if isinstance(c, dict)]


def build_entity_rows(house_doc: dict, profile_id: str) -> list[dict[str, Any]]:
    """Plant + live-profile consumers as mapping entity rows."""
    plant = house_doc.get("plant") if isinstance(house_doc.get("plant"), dict) else {}
    rows: list[dict[str, Any]] = [
        {
            "id": PLANT_ENTITY_ID,
            "kind": "plant",
            "label": "Anlage (Plant)",
            "fields": PLANT_FIELDS,
            "bindings": binding_map(plant.get("ehal_bindings")),
        }
    ]
    consumers = consumers_for_profile(house_doc, profile_id)
    for consumer in consumers:
        cid = _nonempty(consumer.get("id"))
        if not cid:
            continue
        rows.append(
            {
                "id": cid,
                "kind": "consumer",
                "label": _nonempty(consumer.get("label")) or cid,
                "fields": fields_for_consumer(consumer),
                "bindings": binding_map(consumer.get("ehal_bindings")),
                "consumer": consumer,
            }
        )
    return rows


def apply_entity_bindings(
    house_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write bindings onto plant or consumer; return new doc."""
    house = dict(house_doc)
    cleaned = {k: v for k, v in bindings.items() if _nonempty(v)}
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
            consumer["ehal_bindings"] = cleaned
            consumer.pop("event_triggers", None)
            break
    profile["consumers"] = consumers
    house["profiles"] = {**profiles, profile_id: profile}
    return house


def configured_marker_names(house_doc: dict, profile_id: str) -> list[str]:
    names: list[str] = []
    for row in build_entity_rows(house_doc, profile_id):
        names.extend(v for v in row["bindings"].values() if v)
    return names


def session_manual_marker_names() -> list[str]:
    """Session-only Merker names typed in on EHAL-Com (not yet necessarily saved)."""
    raw = st.session_state.get(_SESSION_MANUAL_NAMES) or []
    return [str(n).strip() for n in raw if str(n or "").strip()]


def add_manual_marker_name(
    existing: list[str],
    raw: str,
    *,
    also_known: list[str] | None = None,
) -> tuple[list[str], str | None]:
    """Append a stripped Merker name; return (list, hint) — hint set on empty/duplicate."""
    name = str(raw or "").strip()
    if not name:
        return list(existing), "Leerer Merkername — nichts hinzugefügt."
    key = name.casefold()
    known = list(existing) + list(also_known or [])
    if any(str(n).strip().casefold() == key for n in known if str(n or "").strip()):
        return list(existing), f"`{name}` ist bereits in der Liste."
    return [*existing, name], None


def is_known_marker_name(name: str, options: list[str]) -> bool:
    """True if name matches a non-sentinel option (case-insensitive)."""
    key = str(name or "").strip().casefold()
    if not key or key == _NONE.casefold():
        return False
    return any(
        str(o).strip().casefold() == key for o in options if str(o or "").strip() and o != _NONE
    )


def _name_options(
    rows: list[dict[str, Any]],
    current_values: list[str],
    manual_names: list[str] | None = None,
) -> list[str]:
    names = [str(row.get("name") or "") for row in rows if str(row.get("name") or "").strip()]
    for value in list(current_values) + list(manual_names or []):
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)
    names.sort(key=str.lower)
    return [_NONE] + names




def _clear_pending_for_widget(widget_key: str) -> None:
    pending = st.session_state.get(_SESSION_PENDING_NEW)
    if isinstance(pending, dict) and pending.get("widget_key") == widget_key:
        st.session_state.pop(_SESSION_PENDING_NEW, None)


def _queue_pending_new_marker(
    *,
    entity_id: str,
    profile_id: str,
    field: str,
    name: str,
    widget_key: str,
) -> None:
    st.session_state[_SESSION_PENDING_NEW] = {
        "entity_id": entity_id,
        "profile_id": profile_id,
        "field": field,
        "name": name,
        "widget_key": widget_key,
    }


def _migrate_on_open() -> tuple[dict, dict]:
    """Ensure entity bindings exist; persist house + stripped config once when changed."""
    house = load_house_profiles()
    config_doc = load_main_config()
    new_house, new_config, changed = ensure_migrated(house, config_doc)
    if changed and not st.session_state.get(_SESSION_MIGRATED):
        save_house_profiles(new_house)
        stripped = strip_migrated_config_keys(new_config)
        save_main_config(stripped)
        reset_adapter_cache()
        st.session_state[_SESSION_MIGRATED] = True
        return new_house, stripped
    return new_house if changed else house, config_doc














def _render_field_selects(
    entity: dict[str, Any],
    options: list[str],
    proposals: dict[str, dict[str, Any]],
    *,
    profile_id: str,
) -> dict[str, str]:
    ehal_map: dict[str, str] = {}
    bindings = entity["bindings"]
    fields: tuple[str, ...] = tuple(entity["fields"])
    required = set(TELEMETRY_REQUIRED) if entity["id"] == PLANT_ENTITY_ID else set()
    grouped = group_fields_by_role(fields)
    if not grouped:
        grouped = [("other", list(fields))]
    entity_id = str(entity["id"])
    for role_id, role_fields in grouped:
        caption = role_group_label(role_id) if role_id != "other" else "Felder"
        st.markdown(f"**{caption}** — `{entity_id}`")
        for field in role_fields:
            prop = proposals.get(field) or {}
            default = str(prop.get("marker_name") or bindings.get(field) or "")
            mapped = _select_marker(
                field,
                entity_id=entity_id,
                profile_id=profile_id,
                current=default if default in options else bindings.get(field, ""),
                options=options,
                required=field in required,
                key=f"ehal_lox_map_{entity_id}_{field}",
            )
            if mapped:
                ehal_map[field] = mapped
    return ehal_map




def _validate_mapping_save(entity_id: str, ehal_map: dict[str, str]) -> str | None:
    if entity_id == PLANT_ENTITY_ID:
        missing = [name for name in TELEMETRY_REQUIRED if name not in ehal_map]
        if missing:
            return "Pflichtfelder fehlen: " + ", ".join(missing)
    return None


def _ensure_ehal_loxone_meta(config_doc: dict) -> dict:
    stripped = strip_migrated_config_keys(config_doc)
    ehal = dict(stripped.get("ehal") or {}) if isinstance(stripped.get("ehal"), dict) else {}
    if not ehal.get("backend"):
        ehal["backend"] = "loxone"
    if not ehal.get("adapter_id"):
        ehal["adapter_id"] = "loxone-home"
    stripped["ehal"] = ehal
    return stripped


def _save_entity_mapping(
    house: dict,
    config_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    ehal_map: dict[str, str],
) -> None:
    error = _validate_mapping_save(entity_id, ehal_map)
    if error:
        st.error(error)
        return
    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    updated = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=ehal_map,
    )
    save_house_profiles(updated)
    save_main_config(_ensure_ehal_loxone_meta(migrated_config))
    reset_adapter_cache()
    st.session_state[_SESSION_MIGRATED] = True
    st.success(
        f"Mapping für `{entity_id}` in `house_profiles.json` gespeichert "
        "(Bindings); Legacy-Merker-Trigger und Anlagen-Rollen in config bereinigt."
    )
    st.rerun()

from ui.ehal_loxone_mapping_ui import (  # noqa: E402
    PLANT_ENTITY_ID,
    _NONE,
    _SESSION_ENTITY,
    _SESSION_MANUAL_FEEDBACK,
    _SESSION_MANUAL_NAMES,
    _SESSION_MIGRATED,
    _SESSION_PENDING_NEW,
    _SESSION_PROPOSALS,
    _SESSION_SCAN,
    _accept_pending_new_marker,
    _confirm_new_marker_dialog,
    _manual_add_probe_caption,
    _render_entity_picker,
    _render_http_probe_scan,
    _run_structure_scan,
    _select_marker,
    render_ehal_loxone_mapping_section,
)
