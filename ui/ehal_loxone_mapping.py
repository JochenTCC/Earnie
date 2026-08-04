"""Entity-centric Loxone → EHAL HITL mapping UI (2.4.k)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from house_config.ehal_bindings import (
    FILTER_EHAL_FIELDS,
    FILTER_ENTITY_ID,
    THERMAL_RC_EHAL_FIELDS,
    ehal_map_to_filter_bindings,
    ensure_migrated,
    filter_bindings_to_ehal_map,
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
    if cid:
        base = flex_fields_for_consumer(cid)
    else:
        base = FLEX_FIELDS
    if str(consumer.get("type") or "") == "thermal_rc":
        return base + THERMAL_RC_EHAL_FIELDS
    return base


def _milp_thermal_rc_host(consumers: list[dict]) -> dict | None:
    """First thermal_rc that creates the SwimSpa-filter bridge entity."""
    from house_config.consumption_csv import consumer_uses_profile_csv

    for consumer in consumers:
        if str(consumer.get("type") or "") != "thermal_rc":
            continue
        if consumer_uses_profile_csv(consumer):
            continue
        return consumer
    return None


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
    host = _milp_thermal_rc_host(consumers)
    if host is not None and not any(
        str(c.get("id") or "").strip() == "pool_filter" for c in consumers
    ):
        stored = host.get("swimspa_filter_bindings")
        rows.append(
            {
                "id": FILTER_ENTITY_ID,
                "kind": "filter",
                "label": "Pool / SwimSpa Filter",
                "fields": FILTER_FIELDS,
                "bindings": filter_bindings_to_ehal_map(
                    stored if isinstance(stored, dict) else {}
                ),
                "host_id": _nonempty(host.get("id")),
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
    """Write bindings onto plant, consumer, or filter bridge nest; return new doc."""
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
    if entity_id == FILTER_ENTITY_ID:
        host = _milp_thermal_rc_host(consumers)
        host_id = _nonempty(host.get("id")) if host else ""
        nest = ehal_map_to_filter_bindings(cleaned)
        for consumer in consumers:
            if _nonempty(consumer.get("id")) != host_id:
                continue
            if nest:
                consumer["swimspa_filter_bindings"] = nest
            else:
                consumer.pop("swimspa_filter_bindings", None)
            break
        profile["consumers"] = consumers
        house["profiles"] = {**profiles, profile_id: profile}
        return house
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


def _select_marker(
    field: str,
    *,
    entity_id: str,
    profile_id: str,
    current: str,
    options: list[str],
    required: bool,
    key: str,
) -> str:
    choice = current if current in options else _NONE
    if key not in st.session_state and current and current not in options and current != _NONE:
        # Restore a typed/custom value that is not yet in the shared options list.
        st.session_state[key] = current
    selected = st.selectbox(
        _field_select_caption(field, required=required),
        options=options,
        index=options.index(choice) if choice in options else 0,
        key=key,
        accept_new_options=True,
        help="Bekannten Merker wählen oder neuen Namen eintippen (Bestätigung folgt).",
    )
    if selected is None or selected == _NONE or not str(selected).strip():
        _clear_pending_for_widget(key)
        return ""
    text = str(selected).strip()
    known_pool = options + session_manual_marker_names()
    if is_known_marker_name(text, known_pool):
        _clear_pending_for_widget(key)
        return text
    _queue_pending_new_marker(
        entity_id=entity_id,
        profile_id=profile_id,
        field=field,
        name=text,
        widget_key=key,
    )
    return ""


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


def render_ehal_loxone_mapping_section() -> None:
    """HTTP-probe structure scan + entity HITL; persists plant/consumer ehal_bindings."""
    st.caption(
        "Entity-zentriertes Mapping: Anlage + Verbraucher aus dem Live-Hausprofil. "
        "Bei MILP-`thermal_rc` zusätzlich Entity **Pool / SwimSpa Filter** "
        f"(`{FILTER_ENTITY_ID}`) für `get_filter_remaining_hours` u. a. "
        "Felder `{entity}.{ehal_field}` → Merker; Speichern in `house_profiles.json` "
        "(`plant` / `consumers[].ehal_bindings` / `swimspa_filter_bindings`). "
        "Außerplanmäßige Optimierung: Loxone VO `Earnie_Request_Optimize` "
        "(Daemon-HTTP, Port `system.ehal_loxone_http_port`, Standard 8541). "
        "Struktur-Scan: HTTP-Probe bekannter Earnie_*/gemappter Merker; "
        "in jedem Feld-Dropdown einen neuen Merker eintippen (mit Bestätigung)."
    )
    house, config_doc = _migrate_on_open()
    profile_id = resolve_live_profile_id(house)
    entities = build_entity_rows(house, profile_id)
    if not profile_id:
        st.warning("Kein Hausprofil im Live-Szenario — bitte zuerst im Szenarienkonfigurator setzen.")
        return
    feedback = st.session_state.pop(_SESSION_MANUAL_FEEDBACK, None)
    if feedback:
        st.info(feedback)
    rows = _render_http_probe_scan(house, profile_id)
    entity = _render_entity_picker(entities)
    proposals: dict[str, dict[str, Any]] = dict(st.session_state.get(_SESSION_PROPOSALS) or {})
    options = _name_options(
        rows,
        list(entity["bindings"].values()),
        session_manual_marker_names(),
    )
    ehal_map = _render_field_selects(
        entity,
        options,
        proposals,
        profile_id=profile_id,
    )
    pending = st.session_state.get(_SESSION_PENDING_NEW)
    if isinstance(pending, dict) and str(pending.get("name") or "").strip():
        _confirm_new_marker_dialog(house, config_doc)
    if st.button("Mapping speichern", key="ehal_lox_save_btn", type="primary"):
        _save_entity_mapping(
            house,
            config_doc,
            profile_id=profile_id,
            entity_id=str(entity["id"]),
            ehal_map=ehal_map,
        )


def _render_http_probe_scan(house: dict, profile_id: str) -> list[dict[str, Any]]:
    """Scan via HTTP-Probe only (MCP / Ollama / Quellenvergleich UI removed; code kept in integrations)."""
    if st.button("HTTP-Probe", key="ehal_lox_scan_btn"):
        configured = configured_marker_names(house, profile_id) + session_manual_marker_names()
        _run_structure_scan(configured)
    rows: list[dict[str, Any]] = list(st.session_state.get(_SESSION_SCAN) or [])
    if rows:
        st.caption(f"{len(rows)} Namen für Mapping (HTTP-Probe)")
        st.dataframe(rows[:40], width="stretch", hide_index=True)
        if len(rows) > 40:
            st.caption(f"... und {len(rows) - 40} weitere.")
        errors = st.session_state.get("ehal_lox_scan_errors") or []
        for err in errors[:8]:
            st.caption(err)
    return rows


def _manual_add_probe_caption(name: str) -> str:
    """Non-blocking HTTP presence check after manual add; always keeps the name in the list."""
    host = str(config.get("LOXONE_IP") or "")
    username = str(config.get("LOXONE_USER") or "")
    password = str(config.get("LOXONE_PASS") or "")
    if not host.strip() or not username.strip():
        return (
            f"`{name}` gespeichert und zugeordnet "
            "(keine Loxone-Zugangsdaten — HTTP-Probe übersprungen)."
        )
    try:
        result = probe_marker_names(
            [name],
            host=host,
            username=username,
            password=password,
            timeout_sec=5.0,
        )
    except ValueError as exc:
        return f"`{name}` gespeichert und zugeordnet (Probe fehlgeschlagen: {exc})."
    if name in result.present:
        return f"`{name}` gespeichert und zugeordnet — HTTP-Probe: auf dem Miniserver vorhanden."
    if name in result.missing:
        return (
            f"`{name}` gespeichert und zugeordnet — HTTP-Probe: 404 (fehlt noch); "
            "Mapping trotzdem aktiv."
        )
    return f"`{name}` gespeichert und zugeordnet (Probe ohne eindeutigen Status)."


@st.dialog("Neuer Merker?")
def _confirm_new_marker_dialog(house: dict, config_doc: dict) -> None:
    pending = st.session_state.get(_SESSION_PENDING_NEW) or {}
    name = str(pending.get("name") or "").strip()
    field = str(pending.get("field") or "").strip()
    entity_id = str(pending.get("entity_id") or "").strip()
    st.markdown(
        f"Unbekannter Merker `{name}` für EHAL-Feld `{field}` "
        f"(Entity `{entity_id}`)."
    )
    st.caption("Als neuen Merker speichern und diesem Feld zuordnen?")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Ja, speichern und zuordnen", type="primary", key="ehal_lox_new_yes"):
            _accept_pending_new_marker(house, config_doc)
            st.rerun()
    with col_no:
        if st.button("Nein", key="ehal_lox_new_no"):
            widget_key = str(pending.get("widget_key") or "")
            if widget_key:
                st.session_state[widget_key] = _NONE
            st.session_state.pop(_SESSION_PENDING_NEW, None)
            st.rerun()


def _accept_pending_new_marker(house: dict, config_doc: dict) -> None:
    pending = st.session_state.get(_SESSION_PENDING_NEW) or {}
    name = str(pending.get("name") or "").strip()
    field = str(pending.get("field") or "").strip()
    entity_id = str(pending.get("entity_id") or "").strip()
    profile_id = str(pending.get("profile_id") or "").strip()
    widget_key = str(pending.get("widget_key") or "")
    if not (name and field and entity_id and profile_id):
        st.session_state.pop(_SESSION_PENDING_NEW, None)
        return
    existing = list(st.session_state.get(_SESSION_MANUAL_NAMES) or [])
    updated, _hint = add_manual_marker_name(existing, name)
    st.session_state[_SESSION_MANUAL_NAMES] = updated
    rows = build_entity_rows(house, profile_id)
    entity = next((row for row in rows if row["id"] == entity_id), None)
    bindings = dict(entity["bindings"]) if entity else {}
    bindings[field] = name
    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    saved = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=bindings,
    )
    save_house_profiles(saved)
    save_main_config(_ensure_ehal_loxone_meta(migrated_config))
    reset_adapter_cache()
    if widget_key:
        st.session_state[widget_key] = name
    st.session_state.pop(_SESSION_PENDING_NEW, None)
    st.session_state[_SESSION_MANUAL_FEEDBACK] = _manual_add_probe_caption(name)


def _render_entity_picker(entities: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [f"{row['label']} (`{row['id']}`)" for row in entities]
    ids = [str(row["id"]) for row in entities]
    current = str(st.session_state.get(_SESSION_ENTITY) or PLANT_ENTITY_ID)
    if current not in ids:
        current = ids[0] if ids else PLANT_ENTITY_ID
    st.markdown("#### Entity")
    picked = st.selectbox(
        "Entity",
        options=labels,
        index=ids.index(current) if current in ids else 0,
        key="ehal_lox_entity_pick",
        label_visibility="collapsed",
    )
    entity_id = ids[labels.index(picked)]
    if entity_id != st.session_state.get(_SESSION_ENTITY):
        st.session_state[_SESSION_ENTITY] = entity_id
    return next(row for row in entities if row["id"] == entity_id)


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


def _run_structure_scan(configured: list[str]) -> None:
    """HTTP-Probe only for mapping names. MCP/Ollama remain in integrations for later re-use."""
    st.session_state.pop(_SESSION_PROPOSALS, None)
    result = scan_structure(
        host=str(config.get("LOXONE_IP") or ""),
        username=str(config.get("LOXONE_USER") or ""),
        password=str(config.get("LOXONE_PASS") or ""),
        configured_names=configured,
        mcp_base_url="",
        sources=(SOURCE_HTTP_PROBE,),
        selected_source=SOURCE_HTTP_PROBE,
    )
    st.session_state["ehal_lox_scan_errors"] = result.all_errors()
    items = result.mapping_items(use_source=SOURCE_HTTP_PROBE)
    st.session_state[_SESSION_SCAN] = [
        {
            "name": item.name,
            "uuid": item.uuid,
            "type": item.type,
            "room": item.room,
            "category": item.category,
            "source": item.source,
        }
        for item in items
    ]
    if items:
        st.session_state[_SESSION_PROPOSALS] = heuristic_propose(
            [item.name for item in items],
            fields=PLANT_FIELDS + EV_FIELDS + FLEX_FIELDS + FILTER_FIELDS,
        )


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
