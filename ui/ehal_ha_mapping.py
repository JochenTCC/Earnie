"""HITL Entity → EHAL mapping UI for Home Assistant (2.6.h entity-picker parity)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ehal.models import canonicalize_ha_entity_keys
from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from house_config.ehal_bindings import ensure_migrated
from house_config.ha_ehal_bindings import aggregate_ha_entities
from integrations.ehal_live import reset_adapter_cache
from integrations.ha_adapter import (
    TELEMETRY_ENERGY_OPTIONAL,
    TELEMETRY_REQUIRED,
    HaAdapter,
    HaConfig,
    HaHttpError,
)
from integrations.ha_ehal_mapping import (
    heuristic_propose,
    resolve_field_select_default,
)
from ui.ehal_loxone_mapping import (
    PLANT_ENTITY_ID,
    apply_entity_bindings,
    build_entity_rows,
    resolve_live_profile_id,
)
from ui.house_config_io import (
    load_house_profiles,
    load_main_config,
    save_house_profiles,
    save_main_config,
)

_NONE = "— nicht gemappt —"
_SESSION_SCAN = "ehal_ha_scan_entities"
_SESSION_SCAN_ERROR = "ehal_ha_scan_error"
_SESSION_PROPOSALS = "ehal_ha_proposals"
_SESSION_ENTITY = "ehal_ha_entity_id"
_SESSION_AUTO_SCAN = "ehal_ha_auto_scan_done"

_FIELD_LABELS: dict[str, str] = role_field_labels()
_SIGN_FIELDS = ("sens_grid_power_active", "sens_ess_power")


def _clear_map_widget_keys(entity_id: str, fields: tuple[str, ...] | list[str]) -> None:
    """Drop selectbox keys so defaults re-seed from propose / saved map."""
    for field in fields:
        st.session_state.pop(f"ehal_ha_map_{entity_id}_{field}", None)


def _proposed_entity_id(proposals: dict[str, dict[str, Any]], field: str) -> str:
    entry = proposals.get(field) if isinstance(proposals, dict) else None
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("entity_id") or "").strip()


def _ha_credentials(data: dict) -> dict[str, Any]:
    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    raw_sign = dict(ha.get("sign") or {}) if isinstance(ha.get("sign"), dict) else {}
    return {
        "backend": str(ehal.get("backend") or ""),
        "adapter_id": str(ehal.get("adapter_id") or "earnie-hems"),
        "base_url": str(ha.get("base_url") or "").strip(),
        "token": str(ha.get("token") or "").strip(),
        "sign": canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in raw_sign.items()}
        ),
    }


def _ensure_ha_migrated() -> tuple[dict, dict]:
    """One-shot migrate flat entities → Pattern B; return (config, house)."""
    config_doc = load_main_config()
    house = load_house_profiles()
    new_house, new_config, changed = ensure_migrated(house, config_doc)
    if changed:
        save_house_profiles(new_house)
        save_main_config(new_config)
        return new_config, new_house
    return config_doc, house


def _adapter_from_form(base_url: str, token: str, entities: dict[str, str]) -> HaAdapter:
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token

    resolved_url = resolve_ha_base_url(base_url)
    resolved_token = resolve_ha_token(token)
    if not resolved_url or not resolved_token:
        raise ValueError(
            "URL und Token sind erforderlich "
            "(oder SUPERVISOR_TOKEN beim Betrieb als Home-Assistant-Add-on)."
        )
    return HaAdapter(
        HaConfig(
            base_url=resolved_url,
            token=resolved_token,
            adapter_id="earnie-hems",
            entities=entities,
        )
    )


def _entity_options(rows: list[dict[str, Any]], current_values: list[str]) -> list[str]:
    ids = [str(row["entity_id"]) for row in rows if str(row.get("entity_id") or "").strip()]
    for value in current_values:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    return [_NONE] + ids


def _field_select_caption(field: str, *, required: bool = False) -> str:
    meaning = _FIELD_LABELS.get(field, field)
    suffix = " *" if required else ""
    return f"{meaning} (`{field}`){suffix}"


def _ha_entity_fields(entity: dict[str, Any]) -> tuple[str, ...]:
    """Plant gets Slot-Ist energy counters in addition to Loxone plant fields."""
    fields = tuple(entity.get("fields") or ())
    if str(entity.get("id") or "") != PLANT_ENTITY_ID:
        return fields
    extra = [f for f in TELEMETRY_ENERGY_OPTIONAL if f not in fields]
    return fields + tuple(extra)


def _select_entity(
    field: str,
    *,
    entity_id: str,
    current: str,
    options: list[str],
    required: bool,
) -> str:
    choice = current if current in options else _NONE
    key = f"ehal_ha_map_{entity_id}_{field}"
    if key not in st.session_state or st.session_state.get(key) not in options:
        st.session_state[key] = choice
    selected = st.selectbox(
        _field_select_caption(field, required=required),
        options=options,
        key=key,
    )
    return "" if selected == _NONE else str(selected)


def _render_credentials_form(current: dict[str, Any]) -> tuple[str, str, str]:
    from integrations.ha_supervisor import (
        SUPERVISOR_CORE_BASE_URL,
        supervisor_proxy_available,
    )

    use_supervisor = supervisor_proxy_available()
    default_url = (
        SUPERVISOR_CORE_BASE_URL
        if use_supervisor
        else "http://homeassistant:8123"
    )
    base_url = st.text_input(
        "Home Assistant URL",
        value=current["base_url"] or default_url,
        key="ehal_ha_base_url",
        help=(
            "Vollständige URL inkl. Port, z. B. http://homeassistant:8123 "
            "(Standard-Port 8123; im Add-on oft http://supervisor/core)."
        ),
    ).strip()
    st.caption(
        "HTTP-Port weicht vom Standard ab? Port in der URL angeben "
        "(z. B. `http://homeassistant:8124`)."
    )
    token = st.text_input(
        "Long-Lived Access Token",
        value=current["token"],
        type="password",
        key="ehal_ha_token",
        help=(
            "Optional im Add-on: leer lassen, um SUPERVISOR_TOKEN zu verwenden."
            if use_supervisor
            else None
        ),
    ).strip()
    adapter_id = st.text_input(
        "adapter_id",
        value=current["adapter_id"] or "earnie-hems",
        key="ehal_ha_adapter_id",
    ).strip() or "earnie-hems"
    return base_url, token, adapter_id


def _run_ha_scan(base_url: str, token: str, *, clear_widgets: bool = True) -> None:
    st.session_state.pop(_SESSION_SCAN_ERROR, None)
    st.session_state.pop(_SESSION_PROPOSALS, None)
    try:
        scanned = _adapter_from_form(base_url, token, {}).list_mappable_entities()
        st.session_state[_SESSION_SCAN] = scanned
        st.session_state[_SESSION_PROPOSALS] = heuristic_propose(scanned)
        if clear_widgets:
            entity_id = str(st.session_state.get(_SESSION_ENTITY) or PLANT_ENTITY_ID)
            house = load_house_profiles()
            profile_id = resolve_live_profile_id(house)
            rows = build_entity_rows(house, profile_id) if profile_id else []
            entity = next((r for r in rows if r["id"] == entity_id), None)
            fields = _ha_entity_fields(entity) if entity else ()
            _clear_map_widget_keys(entity_id, fields)
    except (HaHttpError, ValueError, OSError) as exc:
        st.session_state[_SESSION_SCAN] = []
        st.session_state[_SESSION_PROPOSALS] = {}
        st.session_state[_SESSION_SCAN_ERROR] = str(exc)


def _maybe_auto_scan(base_url: str, token: str) -> None:
    """Scan /api/states once per Streamlit session when credentials resolve."""
    if st.session_state.get(_SESSION_SCAN) is not None:
        return
    if st.session_state.get(_SESSION_AUTO_SCAN):
        return
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token

    if not resolve_ha_base_url(base_url) or not resolve_ha_token(token):
        return
    st.session_state[_SESSION_AUTO_SCAN] = True
    _run_ha_scan(base_url, token, clear_widgets=False)


def _render_scan_section(base_url: str, token: str) -> list[dict[str, Any]]:
    _maybe_auto_scan(base_url, token)
    if st.button("Entities scannen", key="ehal_ha_scan_btn"):
        _run_ha_scan(base_url, token, clear_widgets=True)

    scan_error = st.session_state.get(_SESSION_SCAN_ERROR)
    if scan_error:
        st.error(f"Scan fehlgeschlagen: {scan_error}")

    rows: list[dict[str, Any]] = list(st.session_state.get(_SESSION_SCAN) or [])
    if rows:
        st.caption(
            f"{len(rows)} mappable Entities (sensor/number/select/input_number). "
            "Scan einmal pro Session (Button = erneuter Scan)."
        )
        preview = [
            {
                "entity_id": row["entity_id"],
                "name": row.get("friendly_name"),
                "state": row.get("state"),
                "unit": row.get("unit"),
                "device_class": row.get("device_class"),
            }
            for row in rows[:40]
        ]
        st.dataframe(preview, width="stretch", hide_index=True)
        if len(rows) > 40:
            st.caption(f"... und {len(rows) - 40} weitere (Auswahl unten vollständig).")
    return rows


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
        key="ehal_ha_entity_pick",
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
) -> dict[str, str]:
    ehal_map: dict[str, str] = {}
    bindings = entity["bindings"]
    fields = _ha_entity_fields(entity)
    required = set(TELEMETRY_REQUIRED) if entity["id"] == PLANT_ENTITY_ID else set()
    grouped = group_fields_by_role(fields)
    if not grouped:
        grouped = [("other", list(fields))]
    entity_id = str(entity["id"])
    empty_saved = sum(1 for field in fields if not str(bindings.get(field) or ""))
    proposed_for_empty = sum(
        1
        for field in fields
        if not str(bindings.get(field) or "") and _proposed_entity_id(proposals, field)
    )
    if proposals:
        st.caption(
            f"Heuristik: {proposed_for_empty}/{empty_saved} leere Felder vorgeschlagen "
            "(gespeicherte Bindings bleiben unberührt)."
        )
    for role_id, role_fields in grouped:
        caption = role_group_label(role_id) if role_id != "other" else "Felder"
        st.markdown(f"**{caption}** — `{entity_id}`")
        for field in role_fields:
            default = resolve_field_select_default(
                str(bindings.get(field) or ""),
                _proposed_entity_id(proposals, field),
            )
            mapped = _select_entity(
                field,
                entity_id=entity_id,
                current=default,
                options=options,
                required=field in required,
            )
            if mapped:
                ehal_map[field] = mapped
    return ehal_map


def _render_sign_selects(current_sign: dict[str, str]) -> dict[str, str]:
    st.markdown("**Vorzeichen** (nur wenn HA-Entity nicht EHAL-konform ist)")
    sign: dict[str, str] = {}
    for field in _SIGN_FIELDS:
        mode = str(current_sign.get(field) or "ehal").lower()
        if mode not in ("ehal", "negate"):
            mode = "ehal"
        selected = st.selectbox(
            f"Sign `{field}`",
            options=["ehal", "negate"],
            index=0 if mode == "ehal" else 1,
            key=f"ehal_ha_sign_{field}",
            help="ehal = bereits EHAL (+Bezug / +Entladung); negate = Vorzeichen umkehren",
        )
        sign[field] = selected
    return sign


def _validate_mapping_save(entity_id: str, ehal_map: dict[str, str]) -> str | None:
    if entity_id == PLANT_ENTITY_ID:
        missing = [name for name in TELEMETRY_REQUIRED if name not in ehal_map]
        if missing:
            return "Pflichtfelder fehlen: " + ", ".join(missing)
    return None


def _save_entity_mapping(
    house: dict,
    config_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    ehal_map: dict[str, str],
    base_url: str,
    token: str,
    adapter_id: str,
    sign: dict[str, str],
) -> None:
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token

    error = _validate_mapping_save(entity_id, ehal_map)
    if error:
        st.error(error)
        return
    resolved_url = resolve_ha_base_url(base_url)
    if not resolved_url or not resolve_ha_token(token):
        st.error(
            "URL und Token sind erforderlich "
            "(oder SUPERVISOR_TOKEN beim Betrieb als Home-Assistant-Add-on)."
        )
        return
    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    updated = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=ehal_map,
    )
    save_house_profiles(updated)
    payload = dict(migrated_config)
    ehal = dict(payload.get("ehal") or {}) if isinstance(payload.get("ehal"), dict) else {}
    ehal["backend"] = "ha"
    ehal["adapter_id"] = adapter_id
    existing_ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    existing_sign = (
        dict(existing_ha.get("sign") or {})
        if isinstance(existing_ha.get("sign"), dict)
        else {}
    )
    ehal["ha"] = {
        "base_url": resolved_url,
        "token": token,  # never persist SUPERVISOR_TOKEN
        "entities": {},
        "sign": sign if entity_id == PLANT_ENTITY_ID else existing_sign,
    }
    payload["ehal"] = ehal
    save_main_config(payload)
    reset_adapter_cache()
    st.success(
        f"HA-EHAL-Mapping für `{entity_id}` gespeichert "
        "(`plant`/`consumers[].ehal_bindings`, `ehal.backend=ha`)."
    )
    st.rerun()


def render_ehal_ha_mapping_section() -> None:
    """Entity-picker HITL; persists Pattern B bindings + ehal.ha credentials."""
    st.caption(
        "Entity-zentriertes Mapping (wie Loxone): zuerst Entity wählen "
        "(Anlage + Verbraucher aus dem Live-Hausprofil), dann nur deren EHAL-Felder. "
        "Scan einmal pro Session → Heuristik schlägt leere Felder vor → prüfen → "
        "Mapping speichern in `plant` / `consumers[].ehal_bindings`. "
        "Gespeicherte Bindings werden nicht überschrieben. Kein LLM."
    )

    config_doc, house = _ensure_ha_migrated()
    current = _ha_credentials(config_doc)
    base_url, token, adapter_id = _render_credentials_form(current)

    profile_id = resolve_live_profile_id(house)
    if not profile_id:
        st.warning(
            "Kein Hausprofil im Live-Szenario — bitte zuerst im Szenarienkonfigurator setzen."
        )
        return

    entities = build_entity_rows(house, profile_id)
    scan_rows = _render_scan_section(base_url, token)
    entity = _render_entity_picker(entities)
    proposals: dict[str, dict[str, Any]] = dict(
        st.session_state.get(_SESSION_PROPOSALS) or {}
    )
    options = _entity_options(scan_rows, list(entity["bindings"].values()))
    ehal_map = _render_field_selects(entity, options, proposals)

    sign = dict(current["sign"])
    if str(entity["id"]) == PLANT_ENTITY_ID:
        sign = _render_sign_selects(current["sign"])

    col_test, col_save = st.columns(2)
    with col_test:
        test_clicked = st.button("Telemetrie testen", key="ehal_ha_test_read")
    with col_save:
        save_clicked = st.button(
            "Mapping speichern", key="ehal_ha_save_btn", type="primary"
        )

    if test_clicked:
        try:
            # Smoke-test: merge this entity's edits into aggregated live map.
            trial_house = apply_entity_bindings(
                house,
                profile_id=profile_id,
                entity_id=str(entity["id"]),
                bindings=ehal_map,
            )
            entities_map = aggregate_ha_entities(trial_house)
            telemetry = _adapter_from_form(base_url, token, entities_map).read_telemetry()
            st.success("Telemetrie OK")
            st.json(dict(telemetry))
        except (HaHttpError, ValueError, OSError) as exc:
            st.error(f"Telemetrie-Test fehlgeschlagen: {exc}")

    if save_clicked:
        _save_entity_mapping(
            house,
            config_doc,
            profile_id=profile_id,
            entity_id=str(entity["id"]),
            ehal_map=ehal_map,
            base_url=base_url,
            token=token,
            adapter_id=adapter_id,
            sign=sign,
        )
