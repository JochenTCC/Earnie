"""HITL Entity → EHAL mapping UI for Home Assistant (2.4.c)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from ehal.models import canonicalize_ha_entity_keys
from integrations.ehal_live import reset_adapter_cache
from integrations.ha_adapter import (
    SETPOINT_FIELDS,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
    HaAdapter,
    HaConfig,
    HaHttpError,
)
from ui.house_config_io import load_main_config, save_main_config

_NONE = "— nicht gemappt —"
_SESSION_SCAN = "ehal_ha_scan_entities"
_SESSION_SCAN_ERROR = "ehal_ha_scan_error"

_FIELD_LABELS: dict[str, str] = role_field_labels()

_SIGN_FIELDS = ("sens_grid_power_active", "sens_ess_power")


def _ha_block(data: dict) -> dict[str, Any]:
    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    raw_entities = (
        dict(ha.get("entities") or {}) if isinstance(ha.get("entities"), dict) else {}
    )
    raw_sign = dict(ha.get("sign") or {}) if isinstance(ha.get("sign"), dict) else {}
    return {
        "backend": str(ehal.get("backend") or ""),
        "adapter_id": str(ehal.get("adapter_id") or "ha-home"),
        "base_url": str(ha.get("base_url") or "").strip(),
        "token": str(ha.get("token") or "").strip(),
        "entities": canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in raw_entities.items()}
        ),
        "sign": canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in raw_sign.items()}
        ),
    }


def _adapter_from_form(base_url: str, token: str, entities: dict[str, str]) -> HaAdapter:
    return HaAdapter(
        HaConfig(
            base_url=base_url,
            token=token,
            adapter_id="ha-home",
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
    label = _FIELD_LABELS.get(field, field)
    suffix = " *" if required else ""
    choice = current if current in options else _NONE
    selected = st.selectbox(
        f"{label}{suffix}",
        options=options,
        index=options.index(choice) if choice in options else 0,
        key=f"ehal_ha_map_{field}",
    )
    return "" if selected == _NONE else str(selected)


def render_ehal_ha_mapping_section() -> None:
    """Entity-scan + HITL mapping; persists ehal.ha into config.json."""
    st.caption(
        "Human-in-the-Loop: Entities scannen, EHAL-Felder zuweisen, speichern. "
        "Bevorzugt stabile Entities von evcc unter HA. "
        "LLM-gestützte Vorschläge gibt es für Loxone (Ollama) unter Backend Loxone."
    )

    data = load_main_config()
    current = _ha_block(data)

    base_url = st.text_input(
        "Home Assistant URL",
        value=current["base_url"] or "http://homeassistant:8123",
        key="ehal_ha_base_url",
    ).strip()
    token = st.text_input(
        "Long-Lived Access Token",
        value=current["token"],
        type="password",
        key="ehal_ha_token",
    ).strip()
    adapter_id = st.text_input(
        "adapter_id",
        value=current["adapter_id"] or "ha-home",
        key="ehal_ha_adapter_id",
    ).strip() or "ha-home"

    if st.button("Entities scannen", key="ehal_ha_scan_btn"):
        st.session_state.pop(_SESSION_SCAN_ERROR, None)
        try:
            scanned = _adapter_from_form(base_url, token, {}).list_mappable_entities()
            st.session_state[_SESSION_SCAN] = scanned
        except (HaHttpError, ValueError, OSError) as exc:
            st.session_state[_SESSION_SCAN] = []
            st.session_state[_SESSION_SCAN_ERROR] = str(exc)

    scan_error = st.session_state.get(_SESSION_SCAN_ERROR)
    if scan_error:
        st.error(f"Scan fehlgeschlagen: {scan_error}")

    rows: list[dict[str, Any]] = list(st.session_state.get(_SESSION_SCAN) or [])
    if rows:
        st.caption(f"{len(rows)} mappable Entities (sensor/number/select/input_number).")
        preview = [
            {
                "entity_id": row["entity_id"],
                "name": row.get("friendly_name"),
                "state": row.get("state"),
                "unit": row.get("unit"),
            }
            for row in rows[:40]
        ]
        st.dataframe(preview, use_container_width=True, hide_index=True)
        if len(rows) > 40:
            st.caption(f"... und {len(rows) - 40} weitere (Auswahl unten vollständig).")

    options = _entity_options(rows) if rows else [_NONE] + sorted(
        {str(v) for v in current["entities"].values() if str(v).strip()}
    )

    entities: dict[str, str] = {}
    telemetry_fields = TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL
    for role_id, fields in group_fields_by_role(telemetry_fields):
        caption = role_group_label(role_id) if role_id != "other" else "Weitere Telemetrie"
        st.markdown(f"**{caption}** (Telemetrie)")
        for field in fields:
            mapped = _select_entity(
                field,
                current=str(current["entities"].get(field) or ""),
                options=options,
                required=field in TELEMETRY_REQUIRED,
            )
            if mapped:
                entities[field] = mapped

    for role_id, fields in group_fields_by_role(SETPOINT_FIELDS):
        caption = role_group_label(role_id) if role_id != "other" else "Weitere Setpoints"
        st.markdown(f"**{caption}** (Setpoints)")
        for field in fields:
            mapped = _select_entity(
                field,
                current=str(current["entities"].get(field) or ""),
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
        if not base_url or not token:
            st.error("URL und Token sind erforderlich.")
            return
        if missing:
            st.error("Pflichtfelder fehlen: " + ", ".join(missing))
            return
        payload = dict(data)
        ehal = dict(payload.get("ehal") or {}) if isinstance(payload.get("ehal"), dict) else {}
        ehal["backend"] = "ha"
        ehal["adapter_id"] = adapter_id
        ehal["ha"] = {
            "base_url": base_url,
            "token": token,
            "entities": entities,
            "sign": sign,
        }
        payload["ehal"] = ehal
        save_main_config(payload)
        reset_adapter_cache()
        st.success("HA-EHAL-Mapping gespeichert (`ehal.backend=ha`).")
        st.rerun()
