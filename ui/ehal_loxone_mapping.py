"""Entity-centric Loxone → EHAL HITL mapping UI (2.4.k)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from house_config.ehal_bindings import (
    ensure_migrated,
    strip_migrated_config_keys,
)
from integrations.ehal_live import reset_adapter_cache
from integrations.loxone_ehal_mapping import (
    FIELD_LABELS,
    SETPOINT_FIELDS,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
    heuristic_propose,
    ollama_reachable,
    propose_with_ollama,
)
from integrations.loxone_structure import (
    ALL_SOURCES,
    SOURCE_LOXAPP3,
    SOURCE_MCP17,
    SOURCE_UNION,
    StructureCompareResult,
    scan_structure,
)
from ui.form_layout import WIDE_LABEL_RATIOS, labeled_selectbox, labeled_text_input
from ui.house_config_io import (
    get_live_scenario_refs,
    load_house_profiles,
    load_main_config,
    save_house_profiles,
    save_main_config,
)

_NONE = "— nicht gemappt —"
_SESSION_SCAN = "ehal_lox_scan"
_SESSION_COMPARE = "ehal_lox_compare"
_SESSION_PROPOSALS = "ehal_lox_proposals"
_SESSION_USE_SOURCE = "ehal_lox_use_source"
_SESSION_ENTITY = "ehal_lox_entity_id"
_SESSION_TRIGGERS = "ehal_lox_triggers_draft"
_SESSION_MIGRATED = "ehal_lox_migrated_once"

_SOURCE_LABELS = {
    SOURCE_UNION: "Union (alle Quellen)",
    SOURCE_LOXAPP3: "LoxAPP3.json",
    SOURCE_MCP17: "Loxone MCP 17.1",
}

_SIGNAL_TYPES = ("binary", "text", "analog")
_ON_CHANGE_OPTIONS = ("any", "rising", "falling")

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
    "flex.power_name",
    "flex.enable_name",
    "flex.power_setpoint_name",
)

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
}


def _field_label(field: str) -> str:
    labels = {**role_field_labels(), **FIELD_LABELS, **_EXTRA_LABELS}
    return labels.get(field, field)


def _field_select_caption(
    field: str,
    *,
    required: bool = False,
    confidence: float | None = None,
) -> str:
    """Bedeutung + EHAL value name for HITL select labels."""
    meaning = _field_label(field)
    suffix = " *" if required else ""
    conf = f" (Konfidenz {confidence:.0%})" if confidence is not None else ""
    return f"{meaning} (`{field}`){suffix}{conf}"


def _nonempty(value: object) -> str:
    return str(value or "").strip()


def fields_for_consumer(consumer: dict) -> tuple[str, ...]:
    """EHAL mapping fields for a house-profile consumer type."""
    if str(consumer.get("type") or "") == "ev":
        return EV_FIELDS
    return FLEX_FIELDS


def binding_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): _nonempty(v) for k, v in raw.items() if _nonempty(v)}


def trigger_list(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


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
            "triggers": trigger_list(plant.get("event_triggers")),
        }
    ]
    for consumer in consumers_for_profile(house_doc, profile_id):
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
                "triggers": trigger_list(consumer.get("event_triggers")),
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
    triggers: list[dict],
) -> dict:
    """Write bindings/triggers onto plant or matching consumer; return new doc."""
    house = dict(house_doc)
    cleaned = {k: v for k, v in bindings.items() if _nonempty(v)}
    cleaned_triggers = [dict(t) for t in triggers if _nonempty(t.get("id"))]
    if entity_id == PLANT_ENTITY_ID:
        plant = dict(house.get("plant") or {}) if isinstance(house.get("plant"), dict) else {}
        plant["ehal_bindings"] = cleaned
        plant["event_triggers"] = cleaned_triggers
        house["plant"] = plant
        return house
    profiles = house.get("profiles")
    if isinstance(profiles, dict):
        profile = dict(profiles.get(profile_id) or {})
        consumers = [dict(c) for c in (profile.get("consumers") or []) if isinstance(c, dict)]
        for consumer in consumers:
            if _nonempty(consumer.get("id")) == entity_id:
                consumer["ehal_bindings"] = cleaned
                consumer["event_triggers"] = cleaned_triggers
                break
        profile["consumers"] = consumers
        house["profiles"] = {**profiles, profile_id: profile}
        return house
    return house


def configured_marker_names(house_doc: dict, profile_id: str) -> list[str]:
    names: list[str] = []
    for row in build_entity_rows(house_doc, profile_id):
        names.extend(v for v in row["bindings"].values() if v)
    return names


def _name_options(rows: list[dict[str, Any]], current_values: list[str]) -> list[str]:
    names = [str(row.get("name") or "") for row in rows if str(row.get("name") or "").strip()]
    for value in current_values:
        if value and value not in names:
            names.append(value)
    names.sort(key=str.lower)
    return [_NONE] + names


def _select_marker(
    field: str,
    *,
    current: str,
    options: list[str],
    required: bool,
    confidence: float | None,
    key: str,
) -> str:
    choice = current if current in options else _NONE
    selected = st.selectbox(
        _field_select_caption(field, required=required, confidence=confidence),
        options=options,
        index=options.index(choice) if choice in options else 0,
        key=key,
    )
    return "" if selected == _NONE else str(selected)


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
    """Structure compare-all + entity HITL; persists plant/consumer ehal_bindings."""
    st.caption(
        "Entity-zentriertes Mapping: Anlage + Verbraucher aus dem Live-Hausprofil. "
        "Felder `{entity}.{ehal_field}` → Merker; Speichern in `house_profiles.json` "
        "(`plant` / `consumers[].ehal_bindings` + `event_triggers`). "
        "Struktur-Scan und optionale KI-Vorschläge wie zuvor (LoxAPP3 / MCP / Ollama)."
    )
    house, config_doc = _migrate_on_open()
    profile_id = resolve_live_profile_id(house)
    entities = build_entity_rows(house, profile_id)
    if not profile_id:
        st.warning("Kein Hausprofil im Live-Szenario — bitte zuerst im Szenarienkonfigurator setzen.")
        return
    rows, ollama_url, ollama_model, ai_clicked = _render_scan_and_compare(
        house, profile_id
    )
    entity = _render_entity_picker(entities)
    if ai_clicked:
        _run_ai_propose(rows, ollama_url, ollama_model, fields=tuple(entity["fields"]))
    proposals: dict[str, dict[str, Any]] = dict(st.session_state.get(_SESSION_PROPOSALS) or {})
    options = _name_options(rows, list(entity["bindings"].values()))
    ehal_map = _render_field_selects(entity, options, proposals)
    triggers = _render_trigger_editor(entity, ehal_map)
    if st.button("Mapping speichern", key="ehal_lox_save_btn", type="primary"):
        _save_entity_mapping(
            house,
            config_doc,
            profile_id=profile_id,
            entity_id=str(entity["id"]),
            ehal_map=ehal_map,
            triggers=triggers,
        )


def _render_scan_and_compare(
    house: dict, profile_id: str
) -> tuple[list[dict[str, Any]], str, str, bool]:
    mcp_url, ollama_url, ollama_model = _render_scan_inputs()
    col_scan, col_ai = st.columns(2)
    with col_scan:
        scan_clicked = st.button("Alle Quellen testen", key="ehal_lox_scan_btn")
    with col_ai:
        ai_clicked = st.button("KI-Vorschlag (Ollama)", key="ehal_lox_ai_btn")
    if scan_clicked:
        _run_structure_scan(configured_marker_names(house, profile_id), mcp_url)
    compare = st.session_state.get(_SESSION_COMPARE)
    if isinstance(compare, dict) and compare.get("rows"):
        st.markdown("**Quellenvergleich** (Research — noch keine Winner-Entscheidung)")
        st.dataframe(compare["rows"], use_container_width=True, hide_index=True)
        for err in (compare.get("errors") or [])[:8]:
            st.caption(err)
    use_source = _render_source_picker(compare if isinstance(compare, dict) else {})
    rows: list[dict[str, Any]] = list(st.session_state.get(_SESSION_SCAN) or [])
    if rows:
        st.caption(f"{len(rows)} Namen für Mapping ({_SOURCE_LABELS.get(use_source, use_source)})")
        st.dataframe(rows[:40], use_container_width=True, hide_index=True)
        if len(rows) > 40:
            st.caption(f"... und {len(rows) - 40} weitere.")
    return rows, ollama_url, ollama_model, ai_clicked


def _render_scan_inputs() -> tuple[str, str, str]:
    mcp_url = st.text_input(
        "Loxone MCP 17.1 Base-URL (optional)",
        value=str(st.session_state.get("ehal_lox_mcp_url") or ""),
        key="ehal_lox_mcp_url",
        help=(
            "Optional. connect.loxonecloud.com/…/mcp: GET 307→Relay, "
            "OAuth mit LOXONE_USER/PASS, dann control_find/control_describe."
        ),
    ).strip()
    ollama_url = st.text_input(
        "Ollama URL",
        value=str(st.session_state.get("ehal_lox_ollama_url") or "http://127.0.0.1:11434"),
        key="ehal_lox_ollama_url",
    ).strip() or "http://127.0.0.1:11434"
    ollama_model = st.text_input(
        "Ollama Modell",
        value=str(st.session_state.get("ehal_lox_ollama_model") or "llama3.2"),
        key="ehal_lox_ollama_model",
    ).strip() or "llama3.2"
    return mcp_url, ollama_url, ollama_model


def _render_entity_picker(entities: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [f"{row['label']} (`{row['id']}`)" for row in entities]
    ids = [str(row["id"]) for row in entities]
    current = str(st.session_state.get(_SESSION_ENTITY) or PLANT_ENTITY_ID)
    if current not in ids:
        current = ids[0] if ids else PLANT_ENTITY_ID
    picked = st.selectbox(
        "Entity",
        options=labels,
        index=ids.index(current) if current in ids else 0,
        key="ehal_lox_entity_pick",
    )
    entity_id = ids[labels.index(picked)]
    if entity_id != st.session_state.get(_SESSION_ENTITY):
        st.session_state[_SESSION_ENTITY] = entity_id
        st.session_state.pop(_SESSION_TRIGGERS, None)
    return next(row for row in entities if row["id"] == entity_id)


def _render_field_selects(
    entity: dict[str, Any],
    options: list[str],
    proposals: dict[str, dict[str, Any]],
) -> dict[str, str]:
    ehal_map: dict[str, str] = {}
    bindings = entity["bindings"]
    fields: tuple[str, ...] = tuple(entity["fields"])
    required = set(TELEMETRY_REQUIRED) if entity["id"] == PLANT_ENTITY_ID else set()
    grouped = group_fields_by_role(fields)
    if not grouped:
        grouped = [("other", list(fields))]
    for role_id, role_fields in grouped:
        caption = role_group_label(role_id) if role_id != "other" else "Felder"
        st.markdown(f"**{caption}** — `{entity['id']}`")
        for field in role_fields:
            prop = proposals.get(field) or {}
            default = str(prop.get("marker_name") or bindings.get(field) or "")
            conf = prop.get("confidence")
            mapped = _select_marker(
                field,
                current=default if default in options else bindings.get(field, ""),
                options=options,
                required=field in required,
                confidence=float(conf) if conf is not None else None,
                key=f"ehal_lox_map_{entity['id']}_{field}",
            )
            if mapped:
                ehal_map[field] = mapped
    return ehal_map


def _trigger_field_options(entity: dict[str, Any], bindings: dict[str, str]) -> list[str]:
    field_options = sorted(set(list(entity["fields"]) + list(bindings.keys())))
    return field_options or list(entity["fields"])


def _render_trigger_editor(
    entity: dict[str, Any],
    bindings: dict[str, str],
) -> list[dict]:
    st.markdown(f"**Event-Trigger** — `{entity['id']}`")
    st.caption(
        "Trigger beziehen sich auf EHAL-Felder dieser Entity; "
        "Merker-Adresse kommt aus dem Binding."
    )
    draft_key = f"{_SESSION_TRIGGERS}_{entity['id']}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = trigger_list(entity.get("triggers"))
    draft: list[dict] = list(st.session_state[draft_key])
    field_options = _trigger_field_options(entity, bindings)
    if st.button("Trigger hinzufügen", key=f"ehal_lox_trig_add_{entity['id']}"):
        draft.append(
            {
                "id": f"trigger_{len(draft) + 1}",
                "ehal_field": field_options[0] if field_options else "",
                "signal_type": "binary",
                "on_change": "any",
                "label": "",
            }
        )
        st.session_state[draft_key] = draft
        st.rerun()
    return _edit_trigger_draft(draft, draft_key, entity["id"], field_options)


def _edit_trigger_draft(
    draft: list[dict],
    draft_key: str,
    entity_id: str,
    field_options: list[str],
) -> list[dict]:
    updated: list[dict] = []
    remove_index: int | None = None
    for index, trigger in enumerate(draft):
        exp_col, rm_col = st.columns([4, 1], vertical_alignment="top")
        with rm_col:
            if st.button("Entfernen", key=f"ehal_lox_trig_rm_{entity_id}_{index}"):
                remove_index = index
        with exp_col:
            with st.expander(
                f"Trigger {index + 1}: {trigger.get('id') or '—'}",
                expanded=False,
            ):
                updated.append(
                    _render_one_trigger(trigger, index, entity_id, field_options)
                )
    if remove_index is not None:
        del updated[remove_index]
        st.session_state[draft_key] = updated
        st.rerun()
    st.session_state[draft_key] = updated
    return updated


def _option_index(options: tuple[str, ...] | list[str], value: object, default: str) -> int:
    text = str(value or default)
    if text in options:
        return list(options).index(text)
    return 0


def _render_one_trigger(
    trigger: dict,
    index: int,
    entity_id: str,
    field_options: list[str],
) -> dict:
    prefix = f"ehal_lox_trig_{entity_id}_{index}"
    current_field = _nonempty(trigger.get("ehal_field"))
    options = list(field_options)
    if current_field and current_field not in options:
        options = [current_field] + options
    return {
        "id": str(
            labeled_text_input(
                "ID", value=str(trigger.get("id", "")), key=f"{prefix}_id",
                ratios=WIDE_LABEL_RATIOS,
            )
            or ""
        ).strip(),
        "ehal_field": str(
            labeled_selectbox(
                "ehal_field",
                options=options or [""],
                index=_option_index(options or [""], current_field, ""),
                key=f"{prefix}_field",
            )
            or ""
        ).strip(),
        "signal_type": labeled_selectbox(
            "signal_type",
            options=list(_SIGNAL_TYPES),
            index=_option_index(_SIGNAL_TYPES, trigger.get("signal_type"), "binary"),
            key=f"{prefix}_type",
        ),
        "on_change": labeled_selectbox(
            "on_change",
            options=list(_ON_CHANGE_OPTIONS),
            index=_option_index(_ON_CHANGE_OPTIONS, trigger.get("on_change"), "any"),
            key=f"{prefix}_chg",
        ),
        "label": str(
            labeled_text_input(
                "Label", value=str(trigger.get("label", "")), key=f"{prefix}_label",
                ratios=WIDE_LABEL_RATIOS,
            )
            or ""
        ).strip(),
    }


def _render_source_picker(compare: dict[str, Any]) -> str:
    available = [SOURCE_UNION]
    for source in ALL_SOURCES:
        if any(row.get("source") == source for row in (compare.get("rows") or [])):
            available.append(source)
    labels = [_SOURCE_LABELS.get(s, s) for s in available]
    current = str(st.session_state.get(_SESSION_USE_SOURCE) or SOURCE_UNION)
    if current not in available:
        current = SOURCE_UNION
    picked_label = st.selectbox(
        "Namen für Mapping aus",
        options=labels,
        index=labels.index(_SOURCE_LABELS.get(current, current)),
        key="ehal_lox_source_pick",
        help="Research: Union = alle gefundenen Namen; Einzelquelle zum Vergleich.",
    )
    source = next(
        (s for s in available if _SOURCE_LABELS.get(s, s) == picked_label),
        SOURCE_UNION,
    )
    if source != st.session_state.get(_SESSION_USE_SOURCE):
        st.session_state[_SESSION_USE_SOURCE] = source
        _apply_selected_source(source)
    return source


def _apply_selected_source(source: str) -> None:
    raw = st.session_state.get(_SESSION_COMPARE)
    if not isinstance(raw, dict) or "result" not in raw:
        return
    result: StructureCompareResult = raw["result"]
    result.selected_source = source
    items = result.mapping_items(use_source=source)
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
            fields=PLANT_FIELDS + EV_FIELDS + FLEX_FIELDS,
        )


def _run_structure_scan(configured: list[str], mcp_url: str) -> None:
    st.session_state.pop(_SESSION_PROPOSALS, None)
    result = scan_structure(
        host=str(config.get("LOXONE_IP") or ""),
        username=str(config.get("LOXONE_USER") or ""),
        password=str(config.get("LOXONE_PASS") or ""),
        configured_names=configured,
        mcp_base_url=mcp_url,
        selected_source=SOURCE_UNION,
    )
    st.session_state[_SESSION_USE_SOURCE] = SOURCE_UNION
    st.session_state[_SESSION_COMPARE] = {
        "rows": result.comparison_rows(),
        "errors": result.all_errors(),
        "result": result,
    }
    items = result.mapping_items(use_source=SOURCE_UNION)
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
            fields=PLANT_FIELDS + EV_FIELDS + FLEX_FIELDS,
        )


def _run_ai_propose(
    rows: list[dict[str, Any]],
    ollama_url: str,
    ollama_model: str,
    *,
    fields: tuple[str, ...],
) -> None:
    names = [str(row.get("name") or "") for row in rows if row.get("name")]
    if not names:
        st.error("Zuerst alle Quellen testen (Namensliste leer).")
        return
    if not ollama_reachable(ollama_url):
        st.warning(
            "Ollama nicht erreichbar — Heuristik-Vorschläge bleiben aktiv. "
            "Ollama separat installieren (nicht im Earnie-Image)."
        )
        st.session_state[_SESSION_PROPOSALS] = heuristic_propose(names, fields=fields)
        return
    with st.spinner("Ollama mappt Merker → EHAL …"):
        proposals = propose_with_ollama(
            names, base_url=ollama_url, model=ollama_model, fields=fields
        )
    if not proposals:
        st.warning("Ollama lieferte keine Vorschläge — Heuristik wird genutzt.")
        proposals = heuristic_propose(names, fields=fields)
    else:
        st.success(f"{len(proposals)} KI-Vorschläge übernommen.")
    st.session_state[_SESSION_PROPOSALS] = proposals


def _validate_mapping_save(
    entity_id: str, ehal_map: dict[str, str], triggers: list[dict]
) -> str | None:
    if entity_id == PLANT_ENTITY_ID:
        missing = [name for name in TELEMETRY_REQUIRED if name not in ehal_map]
        if missing:
            return "Pflichtfelder fehlen: " + ", ".join(missing)
    for item in triggers:
        if item.get("id") and not item.get("ehal_field"):
            return f"Trigger '{item['id']}' braucht ehal_field."
        field = item.get("ehal_field")
        if item.get("id") and field and field not in ehal_map:
            return (
                f"Trigger '{item['id']}': Feld '{field}' "
                "muss gemappt sein (Binding)."
            )
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
    triggers: list[dict],
) -> None:
    error = _validate_mapping_save(entity_id, ehal_map, triggers)
    if error:
        st.error(error)
        return
    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    updated = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=ehal_map,
        triggers=triggers,
    )
    save_house_profiles(updated)
    save_main_config(_ensure_ehal_loxone_meta(migrated_config))
    reset_adapter_cache()
    st.session_state[_SESSION_MIGRATED] = True
    st.success(
        f"Mapping für `{entity_id}` in `house_profiles.json` gespeichert "
        "(Bindings + Trigger); `system.event_triggers` / Anlagen-Merker in config bereinigt."
    )
    st.rerun()
