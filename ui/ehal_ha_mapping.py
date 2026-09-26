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
    binding_conversion_hint,
    binding_unit_issues,
    compatible_entity_ids,
    heuristic_propose,
    resolve_field_select_default,
)
from runtime_store.ehal_setup import BACKEND_HA, default_adapter_id, resolve_adapter_id
from ui.ehal_function_status import (
    render_control_capability_warnings,
    render_function_status,
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
    from runtime_store.dotenv_io import read_ha_credentials

    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    raw_sign = dict(ha.get("sign") or {}) if isinstance(ha.get("sign"), dict) else {}
    base_url, token = read_ha_credentials()
    return {
        "backend": str(ehal.get("backend") or ""),
        "adapter_id": resolve_adapter_id(ehal.get("adapter_id"), BACKEND_HA),
        "base_url": base_url,
        "token": token,
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
            adapter_id=default_adapter_id(BACKEND_HA),
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
    scan_rows: list[dict[str, Any]],
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


def _validate_mapping_save(
    entity_id: str,
    ehal_map: dict[str, str],
    scan_rows: list[dict[str, Any]] | None = None,
) -> str | None:
    if entity_id == PLANT_ENTITY_ID:
        missing = [name for name in TELEMETRY_REQUIRED if name not in ehal_map]
        if missing:
            return "Pflichtfelder fehlen: " + ", ".join(missing)
    issues = binding_unit_issues(ehal_map, scan_rows or [])
    if issues:
        return "Einheit passt nicht zum Feld: " + "; ".join(issues)
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
    scan_rows: list[dict[str, Any]] | None = None,
) -> None:
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token
    from runtime_store.dotenv_io import write_ha_dotenv
    from runtime_store.dotenv_loader import load_app_dotenv

    error = _validate_mapping_save(entity_id, ehal_map, scan_rows)
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
    try:
        # Never persist SUPERVISOR_TOKEN — empty token stays empty in .env.
        write_ha_dotenv(resolved_url, token)
    except (OSError, PermissionError) as exc:
        st.error(f"Speichern der .env fehlgeschlagen: {exc}")
        return
    load_app_dotenv(override=True)
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


def _render_ha_mapping_intro() -> None:
    st.caption(
        "Entity-zentriertes Mapping (wie Loxone): zuerst Entity wählen "
        "(Anlage + Verbraucher aus dem Live-Hausprofil), dann nur deren EHAL-Felder. "
        "Scan einmal pro Session → Heuristik schlägt leere Felder vor → prüfen → "
        "Mapping speichern in `plant` / `consumers[].ehal_bindings`. "
        "Zugangsdaten in `config/.env` (`EHAL_HA_*`). "
        "Gespeicherte Bindings werden nicht überschrieben. Kein LLM."
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
) -> None:
    base_url, token = credentials
    try:
        # Smoke-test: merge this entity's edits into aggregated live map.
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


def _persist_ha_ess_force(house: dict, force: dict[str, Any] | None) -> dict:
    """Write or clear plant.ha_ess_force on the house document."""
    out = dict(house)
    plant = dict(out.get("plant") or {}) if isinstance(out.get("plant"), dict) else {}
    if force:
        plant["ha_ess_force"] = force
    else:
        plant.pop("ha_ess_force", None)
    if plant:
        out["plant"] = plant
    elif "plant" in out and not plant:
        out.pop("plant", None)
    return out


def render_ehal_ha_mapping_section() -> None:
    """Entity-picker HITL; persists Pattern B bindings; HA secrets in .env."""
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

    entities = build_entity_rows(house, profile_id)
    scan_rows = _render_scan_section(base_url, token)
    entity = _render_entity_picker(entities)
    proposals: dict[str, dict[str, Any]] = dict(
        st.session_state.get(_SESSION_PROPOSALS) or {}
    )
    ehal_map = _render_field_selects(entity, scan_rows, proposals)
    ha_ess_force = None
    if str(entity["id"]) == PLANT_ENTITY_ID:
        ha_ess_force = _render_ha_ess_force(house)
    from house_config.ha_ess_force import ha_ess_force_enables_ess_active

    vendor = ha_ess_force_enables_ess_active(ha_ess_force)
    render_function_status(
        ehal_map, _ha_entity_fields(entity), vendor_ess_active=vendor
    )
    try:
        import config as app_config

        control = str(app_config.get_battery_params().get("control") or "full")
    except Exception:
        control = "full"
    if str(entity["id"]) == PLANT_ENTITY_ID:
        render_control_capability_warnings(
            control=control,
            ehal_map=ehal_map,
            ha_ess_force=ha_ess_force,
        )

    sign = dict(current["sign"])
    if str(entity["id"]) == PLANT_ENTITY_ID:
        sign = _render_sign_selects(current["sign"])

    test_clicked, save_clicked = _render_mapping_action_buttons()

    if test_clicked:
        _run_telemetry_smoke_test(
            house,
            profile_id=profile_id,
            entity_id=str(entity["id"]),
            ehal_map=ehal_map,
            credentials=(base_url, token),
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
        )
