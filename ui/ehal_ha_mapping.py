"""HITL Entity → EHAL mapping UI for Home Assistant (2.6.h entity-picker parity)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ehal.profiles import group_fields_by_role, role_group_label
from house_config.ha_ehal_bindings import aggregate_ha_entities
from integrations.ha_adapter import (
    HaHttpError,
)
from integrations.ha_ehal_mapping import (
    binding_conversion_hint,
    compatible_entity_ids,
    heuristic_propose,
    resolve_field_select_default,
)
from runtime_store.ehal_setup import BACKEND_HA, default_adapter_id, resolve_adapter_id
from ui.ehal_function_status import (
    render_control_capability_warnings,
    render_function_status,
    render_inverter_control_capability_warnings,
)
from ehal.ess_fields import ess_field
from ui.ehal_loxone_mapping import (
    BATTERY_ENTITY_KIND,
    PLANT_ENTITY_ID,
    PLANT_TELEMETRY_REQUIRED,
    PV_ENTITY_KIND,
    apply_battery_bindings,
    apply_entity_bindings,
    apply_inverter_bindings,
    apply_pv_system_bindings,
    build_entity_rows,
    entity_kind_for_id,
    INVERTER_ENTITY_KIND,
    resolve_live_profile_id,
)
from ui.house_config_io import (
    load_house_profiles,
)
from ui.ehal_ha_mapping_common import (  # noqa: F401  (re-exported)
    _FIELD_LABELS,
    _NONE,
    _PLANT_SIGN_FIELDS,
    _SESSION_AUTO_SCAN,
    _SESSION_ENTITY,
    _SESSION_PROPOSALS,
    _SESSION_SCAN,
    _SESSION_SCAN_ERROR,
    _adapter_from_form,
    _clear_map_widget_keys,
    _ensure_ha_migrated,
    _entity_options,
    _field_select_caption,
    _ha_credentials,
    _ha_entity_fields,
    _proposed_entity_id,
)
from ui.ehal_ha_mapping_save import (  # noqa: F401  (re-exported)
    _persist_ha_ess_force,
    _save_entity_mapping,
    _validate_mapping_save,
)




















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
        value=resolve_adapter_id(current.get("adapter_id"), BACKEND_HA),
        key="ehal_ha_adapter_id",
    ).strip() or default_adapter_id(BACKEND_HA)
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
            f"{len(rows)} mappable Entities (sensor/number/select/switch/…). "
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
    scan_rows: list[dict[str, Any]],
    proposals: dict[str, dict[str, Any]],
) -> dict[str, str]:
    ehal_map: dict[str, str] = {}
    bindings = entity["bindings"]
    fields = _ha_entity_fields(entity)
    required: set[str] = set()
    if entity["id"] == PLANT_ENTITY_ID:
        required = set(PLANT_TELEMETRY_REQUIRED)
    elif str(entity.get("kind") or "") == BATTERY_ENTITY_KIND:
        required = {ess_field(str(entity["id"]), "sens_ess_soc")}
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
            from ehal.ess_fields import ess_field_kind

            kind = ess_field_kind(field)
            proposed = (
                ""
                if kind == "set_ess_source_select" or field == "set_ess_source_select"
                else _proposed_entity_id(proposals, field)
            )
            default = resolve_field_select_default(
                str(bindings.get(field) or ""),
                proposed,
            )
            # Rule 1: only physically compatible entities are offered.
            options = _entity_options(
                [{"entity_id": eid} for eid in compatible_entity_ids(field, scan_rows)],
                [str(bindings.get(field) or "")],
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
                # Rule 2: factor comes from the HA unit at runtime.
                hint = binding_conversion_hint(field, mapped, scan_rows)
                if hint:
                    st.caption(f"Einheit wird automatisch umgerechnet: {hint}")
    return ehal_map


def _render_sign_selects(
    current_sign: dict[str, str],
    fields: tuple[str, ...] = _PLANT_SIGN_FIELDS,
    *,
    inherit_from: dict[str, str] | None = None,
) -> dict[str, str]:
    st.markdown("**Vorzeichen** (nur wenn HA-Entity nicht EHAL-konform ist)")
    sign: dict[str, str] = {}
    for field in fields:
        inherited = ""
        if inherit_from and field not in current_sign:
            kind = field.split(".")[-1] if field.startswith("ess.") else field
            inherited = str(inherit_from.get(kind) or inherit_from.get(field) or "")
        default = str(current_sign.get(field) or inherited or "ehal").lower()
        if default not in ("ehal", "negate"):
            default = "ehal"
        selected = st.selectbox(
            f"Sign `{field}`",
            options=["ehal", "negate"],
            index=0 if default == "ehal" else 1,
            key=f"ehal_ha_sign_{field}",
            help="ehal = bereits EHAL (+Bezug / +Entladung); negate = Vorzeichen umkehren",
        )
        sign[field] = selected
    return sign






def _render_ha_mapping_intro() -> None:
    from runtime_store.shadow.mode import is_shadow_config_readonly

    st.caption(
        "Entity-zentriertes Mapping (entity-scoped): zuerst Entity wählen "
        "(Anlage, Batterien aus `components.json`, Verbraucher aus dem Live-Hausprofil), "
        "dann nur deren EHAL-Felder. "
        "Scan einmal pro Session → Heuristik schlägt leere Felder vor → prüfen → "
        "Mapping speichern in `plant` / `batteries[].ehal_bindings` / "
        "`consumers[].ehal_bindings`. "
        "Zugangsdaten in `config/.env` (`EHAL_HA_*`). "
        "Gespeicherte Bindings werden nicht überschrieben. Kein LLM."
    )
    if is_shadow_config_readonly():
        st.info(
            "Shadow-Modus: Mapping-Speichern schreibt nur das Runtime-Overlay "
            "`shadow_ehal_bindings.json` (Prod-Config und `.env` bleiben schreibgeschützt)."
        )


def _render_mapping_action_buttons() -> tuple[bool, bool]:
    col_test, col_save = st.columns(2)
    with col_test:
        test_clicked = st.button("Telemetrie testen", key="ehal_ha_test_read")
    with col_save:
        save_clicked = st.button(
            "Mapping speichern", key="ehal_ha_save_btn", type="primary"
        )
    return bool(test_clicked), bool(save_clicked)


def _run_telemetry_smoke_test(
    house: dict,
    *,
    profile_id: str,
    entity_id: str,
    ehal_map: dict[str, str],
    credentials: tuple[str, str],
    entity_kind: str = "",
) -> None:
    from ui.house_config_io import _load_components_document

    base_url, token = credentials
    try:
        kind = str(entity_kind or "").strip() or entity_kind_for_id(
            house, profile_id, entity_id
        )
        if kind == BATTERY_ENTITY_KIND:
            trial_components = apply_battery_bindings(
                _load_components_document(),
                battery_id=entity_id,
                bindings=ehal_map,
            )
            entities_map = aggregate_ha_entities(
                house, components_doc=trial_components
            )
        elif kind == INVERTER_ENTITY_KIND:
            trial_components = apply_inverter_bindings(
                _load_components_document(),
                inverter_id=entity_id,
                bindings=ehal_map,
            )
            entities_map = aggregate_ha_entities(
                house, components_doc=trial_components
            )
        elif kind == PV_ENTITY_KIND:
            trial_components = apply_pv_system_bindings(
                _load_components_document(),
                pv_system_id=entity_id,
                bindings=ehal_map,
            )
            entities_map = aggregate_ha_entities(
                house, components_doc=trial_components
            )
        else:
            trial_house = apply_entity_bindings(
                house,
                profile_id=profile_id,
                entity_id=entity_id,
                bindings=ehal_map,
            )
            entities_map = aggregate_ha_entities(trial_house)
        telemetry = _adapter_from_form(base_url, token, entities_map).read_telemetry()
        st.success("Telemetrie OK")
        st.json(dict(telemetry))
    except (HaHttpError, ValueError, OSError) as exc:
        st.error(f"Telemetrie-Test fehlgeschlagen: {exc}")


def _render_ha_ess_force(house: dict) -> dict[str, Any] | None:
    """Optional Huawei force-charge via HA services (plant.ha_ess_force)."""
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    existing = plant.get("ha_ess_force") if isinstance(plant.get("ha_ess_force"), dict) else {}
    st.markdown("##### Huawei Force (optional)")
    st.caption(
        "Wenn kein `set_ess_active_power`-Entity existiert: "
        "`huawei_solar.forcible_charge` / `forcible_discharge` "
        "(Elevate permissions in der Integration nötig)."
    )
    enabled = st.checkbox(
        "Huawei Force aktivieren",
        value=bool(existing.get("device_id")),
        key="ehal_ha_ess_force_enabled",
    )
    if not enabled:
        return None
    device_id = st.text_input(
        "HA device_id (Batterie/LUNA)",
        value=str(existing.get("device_id") or ""),
        key="ehal_ha_ess_force_device_id",
    )
    duration = st.number_input(
        "Dauer je Zyklus (min)",
        min_value=1,
        max_value=1440,
        value=int(existing.get("duration_min") or 20),
        key="ehal_ha_ess_force_duration",
    )
    device_id = str(device_id or "").strip()
    if not device_id:
        st.warning("device_id fehlt — Force bleibt deaktiviert bis gesetzt.")
        return None
    return {
        "driver": "huawei_solar",
        "device_id": device_id,
        "duration_min": int(duration),
    }




def _render_capability_warnings(
    entity: dict[str, Any],
    kind: str,
    ehal_map: dict[str, str],
    ha_ess_force: dict[str, Any] | None,
) -> None:
    """Control-capability warnings for plant/battery/inverter entities."""
    try:
        import config as app_config

        control = str(app_config.get_battery_params().get("control") or "full")
    except Exception:
        control = "full"
    if str(entity["id"]) == PLANT_ENTITY_ID or kind == BATTERY_ENTITY_KIND:
        bat_control = control
        if kind == BATTERY_ENTITY_KIND:
            bat = entity.get("battery") if isinstance(entity.get("battery"), dict) else {}
            bat_control = str(bat.get("control") or control)
        render_control_capability_warnings(
            control=bat_control,
            ehal_map=ehal_map,
            ha_ess_force=ha_ess_force if kind != BATTERY_ENTITY_KIND else None,
        )
    elif kind == INVERTER_ENTITY_KIND:
        inv = entity.get("inverter") if isinstance(entity.get("inverter"), dict) else {}
        inv_control = str(inv.get("control") or "full")
        render_inverter_control_capability_warnings(
            control=inv_control, ehal_map=ehal_map
        )


def _render_entity_sign(
    entity: dict[str, Any], kind: str, current_sign: dict[str, str]
) -> dict[str, str]:
    """Sign selects for plant / battery entities; other entities keep the current map."""
    sign = dict(current_sign)
    if str(entity["id"]) == PLANT_ENTITY_ID:
        sign = _render_sign_selects(current_sign)
    elif kind == BATTERY_ENTITY_KIND:
        power_field = ess_field(str(entity["id"]), "sens_ess_power")
        sign = _render_sign_selects(
            current_sign,
            (power_field,),
            inherit_from=current_sign,
        )
    return sign


def _render_entity_mapping_body(
    *,
    house: dict[str, Any],
    config_doc: dict[str, Any],
    current: dict[str, Any],
    profile_id: str,
    base_url: str,
    token: str,
    adapter_id: str,
) -> None:
    """Entity picker, field selects, plant extras, and save/test actions."""
    entities = build_entity_rows(house, profile_id)
    scan_rows = _render_scan_section(base_url, token)
    entity = _render_entity_picker(entities)
    proposals: dict[str, dict[str, Any]] = dict(
        st.session_state.get(_SESSION_PROPOSALS) or {}
    )
    ehal_map = _render_field_selects(entity, scan_rows, proposals)
    kind = str(entity.get("kind") or "")
    ha_ess_force = None
    if str(entity["id"]) == PLANT_ENTITY_ID:
        ha_ess_force = _render_ha_ess_force(house)
    from house_config.ha_ess_force import ha_ess_force_enables_ess_active

    vendor = ha_ess_force_enables_ess_active(ha_ess_force)
    render_function_status(
        ehal_map, _ha_entity_fields(entity), vendor_ess_active=vendor
    )
    _render_capability_warnings(entity, kind, ehal_map, ha_ess_force)

    sign = _render_entity_sign(entity, kind, current["sign"])

    test_clicked, save_clicked = _render_mapping_action_buttons()
    if test_clicked:
        _run_telemetry_smoke_test(
            house,
            profile_id=profile_id,
            entity_id=str(entity["id"]),
            ehal_map=ehal_map,
            credentials=(base_url, token),
            entity_kind=kind,
        )
    if save_clicked:
        house_to_save = (
            _persist_ha_ess_force(house, ha_ess_force)
            if str(entity["id"]) == PLANT_ENTITY_ID
            else house
        )
        _save_entity_mapping(
            house_to_save,
            config_doc,
            profile_id=profile_id,
            entity_id=str(entity["id"]),
            ehal_map=ehal_map,
            base_url=base_url,
            token=token,
            adapter_id=adapter_id,
            sign=sign,
            scan_rows=scan_rows,
            entity_kind=kind,
        )


def render_ehal_ha_mapping_section() -> None:
    """Entity-picker HITL; persists entity-scoped bindings; HA secrets in .env."""
    _render_ha_mapping_intro()

    config_doc, house = _ensure_ha_migrated()
    current = _ha_credentials(config_doc)
    base_url, token, adapter_id = _render_credentials_form(current)

    profile_id = resolve_live_profile_id(house)
    if not profile_id:
        st.warning(
            "Kein Hausprofil im Live-Szenario — bitte zuerst im Szenarienkonfigurator setzen."
        )
        return

    _render_entity_mapping_body(
        house=house,
        config_doc=config_doc,
        current=current,
        profile_id=profile_id,
        base_url=base_url,
        token=token,
        adapter_id=adapter_id,
    )
