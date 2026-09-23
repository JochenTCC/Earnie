"""HITL Entity → EHAL mapping UI for Home Assistant (Pattern B persist, 2.6.g)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from ehal.models import canonicalize_ha_entity_keys
from house_config.ehal_bindings import ensure_migrated
from house_config.ha_ehal_bindings import (
    aggregate_ha_entities,
    apply_ha_entities_to_house,
)
from integrations.ehal_live import reset_adapter_cache
from integrations.ha_adapter import (
    SETPOINT_FIELDS,
    TELEMETRY_ENERGY_OPTIONAL,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
    HaAdapter,
    HaConfig,
    HaHttpError,
)
from integrations.ha_ehal_mapping import (
    EHAL_HA_FIELDS,
    heuristic_propose,
    resolve_field_select_default,
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

_FIELD_LABELS: dict[str, str] = role_field_labels()

_SIGN_FIELDS = ("sens_grid_power_active", "sens_ess_power")


def _clear_map_widget_keys() -> None:
    """Drop selectbox keys so defaults re-seed from propose / saved map."""
    for field in EHAL_HA_FIELDS:
        st.session_state.pop(f"ehal_ha_map_{field}", None)


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


def _ensure_ha_migrated() -> tuple[dict, dict[str, str]]:
    """One-shot migrate flat entities → Pattern B; return (config, aggregated map)."""
    config_doc = load_main_config()
    house = load_house_profiles()
    new_house, new_config, changed = ensure_migrated(house, config_doc)
    if changed:
        save_house_profiles(new_house)
        save_main_config(new_config)
        config_doc = new_config
        house = new_house
    entities = aggregate_ha_entities(house)
    return config_doc, entities


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


def _entity_options(rows: list[dict[str, Any]]) -> list[str]:
    return [_NONE] + [str(row["entity_id"]) for row in rows]


def _select_entity(
    field: str,
    *,
    current: str,
    options: list[str],
    required: bool,
) -> str:
    meaning = _FIELD_LABELS.get(field, field)
    suffix = " *" if required else ""
    choice = current if current in options else _NONE
    key = f"ehal_ha_map_{field}"
    # Streamlit keyed selectbox ignores index= after first registration; seed
    # session_state explicitly so scan→propose can re-bind empty fields.
    if key not in st.session_state or st.session_state.get(key) not in options:
        st.session_state[key] = choice
    selected = st.selectbox(
        f"{meaning} (`{field}`){suffix}",
        options=options,
        key=key,
    )
    return "" if selected == _NONE else str(selected)


def render_ehal_ha_mapping_section() -> None:
    """Entity-scan + HITL mapping; persists Pattern B bindings + ehal.ha credentials."""
    from integrations.ha_supervisor import (
        SUPERVISOR_CORE_BASE_URL,
        resolve_ha_base_url,
        resolve_ha_token,
        supervisor_proxy_available,
    )

    st.caption(
        "Human-in-the-Loop: Entities scannen → Heuristik schlägt leere Felder vor → "
        "prüfen → Mapping speichern in `plant` / `consumers[].ehal_bindings`. "
        "Gespeicherte Bindings werden nicht überschrieben. "
        "Kein LLM für HA (analog Loxone-Heuristik)."
    )

    data, saved_entities = _ensure_ha_migrated()
    current = _ha_credentials(data)
    current_entities = saved_entities
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

    if st.button("Entities scannen", key="ehal_ha_scan_btn"):
        st.session_state.pop(_SESSION_SCAN_ERROR, None)
        st.session_state.pop(_SESSION_PROPOSALS, None)
        try:
            scanned = _adapter_from_form(base_url, token, {}).list_mappable_entities()
            st.session_state[_SESSION_SCAN] = scanned
            st.session_state[_SESSION_PROPOSALS] = heuristic_propose(scanned)
            _clear_map_widget_keys()
        except (HaHttpError, ValueError, OSError) as exc:
            st.session_state[_SESSION_SCAN] = []
            st.session_state[_SESSION_PROPOSALS] = {}
            st.session_state[_SESSION_SCAN_ERROR] = str(exc)

    scan_error = st.session_state.get(_SESSION_SCAN_ERROR)
    if scan_error:
        st.error(f"Scan fehlgeschlagen: {scan_error}")

    rows: list[dict[str, Any]] = list(st.session_state.get(_SESSION_SCAN) or [])
    proposals: dict[str, dict[str, Any]] = dict(
        st.session_state.get(_SESSION_PROPOSALS) or {}
    )
    if rows:
        st.caption(f"{len(rows)} mappable Entities (sensor/number/select/input_number).")
        empty_saved = sum(
            1 for field in EHAL_HA_FIELDS if not str(current_entities.get(field) or "")
        )
        proposed_for_empty = sum(
            1
            for field in EHAL_HA_FIELDS
            if not str(current_entities.get(field) or "")
            and _proposed_entity_id(proposals, field)
        )
        if proposals:
            st.caption(
                f"Heuristik: {proposed_for_empty}/{empty_saved} leere Felder vorgeschlagen "
                "(gespeicherte Bindings bleiben unberührt)."
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

    options = _entity_options(rows) if rows else [_NONE] + sorted(
        {str(v) for v in current_entities.values() if str(v).strip()}
    )

    entities: dict[str, str] = {}
    telemetry_fields = TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL
    for role_id, fields in group_fields_by_role(telemetry_fields):
        caption = role_group_label(role_id) if role_id != "other" else "Weitere Telemetrie"
        st.markdown(f"**{caption}** (Telemetrie)")
        for field in fields:
            default = resolve_field_select_default(
                str(current_entities.get(field) or ""),
                _proposed_entity_id(proposals, field),
            )
            mapped = _select_entity(
                field,
                current=default,
                options=options,
                required=field in TELEMETRY_REQUIRED,
            )
            if mapped:
                entities[field] = mapped

    for role_id, fields in group_fields_by_role(TELEMETRY_ENERGY_OPTIONAL):
        caption = (
            role_group_label(role_id) if role_id != "other" else "Weitere Energiezähler"
        )
        st.markdown(f"**{caption}** (Energiezähler für Slot-Ist ΔkWh, optional)")
        for field in fields:
            default = resolve_field_select_default(
                str(current_entities.get(field) or ""),
                _proposed_entity_id(proposals, field),
            )
            mapped = _select_entity(
                field,
                current=default,
                options=options,
                required=False,
            )
            if mapped:
                entities[field] = mapped

    for role_id, fields in group_fields_by_role(SETPOINT_FIELDS):
        caption = role_group_label(role_id) if role_id != "other" else "Weitere Setpoints"
        st.markdown(f"**{caption}** (Setpoints)")
        for field in fields:
            default = resolve_field_select_default(
                str(current_entities.get(field) or ""),
                _proposed_entity_id(proposals, field),
            )
            mapped = _select_entity(
                field,
                current=default,
                options=options,
                required=False,
            )
            if mapped:
                entities[field] = mapped

    st.markdown("**Vorzeichen** (nur wenn HA-Entity nicht EHAL-konform ist)")
    sign: dict[str, str] = {}
    for field in _SIGN_FIELDS:
        mode = str(current["sign"].get(field) or "ehal").lower()
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

    col_test, col_save = st.columns(2)
    with col_test:
        test_clicked = st.button("Telemetrie testen", key="ehal_ha_test_read")
    with col_save:
        save_clicked = st.button(
            "Mapping speichern", key="ehal_ha_save_btn", type="primary"
        )

    if test_clicked:
        try:
            telemetry = _adapter_from_form(base_url, token, entities).read_telemetry()
            st.success("Telemetrie OK")
            st.json(dict(telemetry))
        except (HaHttpError, ValueError, OSError) as exc:
            st.error(f"Telemetrie-Test fehlgeschlagen: {exc}")

    if save_clicked:
        missing = [name for name in TELEMETRY_REQUIRED if name not in entities]
        resolved_url = resolve_ha_base_url(base_url)
        if not resolved_url or not resolve_ha_token(token):
            st.error(
                "URL und Token sind erforderlich "
                "(oder SUPERVISOR_TOKEN beim Betrieb als Home-Assistant-Add-on)."
            )
            return
        if missing:
            st.error("Pflichtfelder fehlen: " + ", ".join(missing))
            return
        house = apply_ha_entities_to_house(load_house_profiles(), entities)
        save_house_profiles(house)
        payload = dict(data)
        ehal = dict(payload.get("ehal") or {}) if isinstance(payload.get("ehal"), dict) else {}
        ehal["backend"] = "ha"
        ehal["adapter_id"] = adapter_id
        ehal["ha"] = {
            "base_url": resolved_url,
            "token": token,  # never persist SUPERVISOR_TOKEN
            "entities": {},
            "sign": sign,
        }
        payload["ehal"] = ehal
        save_main_config(payload)
        reset_adapter_cache()
        st.success(
            "HA-EHAL-Mapping gespeichert "
            "(`plant`/`consumers[].ehal_bindings`, `ehal.backend=ha`)."
        )
        st.rerun()
