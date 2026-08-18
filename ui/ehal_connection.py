"""EHAL connection forms (Loxone/HA/OpenEMS) — backend persistence and credentials."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations.ehal_live import reset_adapter_cache
from runtime_store.ehal_setup import BACKEND_HA, BACKEND_LOXONE, BACKEND_OPENEMS, normalize_backend
from ui.house_config_io import load_main_config, save_main_config


def _ehal_block(data: dict) -> dict[str, Any]:
    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    return dict(ehal)


def persist_ehal_backend(backend: str) -> None:
    """Write ehal.backend and reload runtime config."""
    resolved = normalize_backend(backend)
    data = load_main_config()
    ehal = _ehal_block(data)
    if resolved == BACKEND_LOXONE:
        ehal["backend"] = "loxone"
    else:
        ehal["backend"] = resolved
    data["ehal"] = ehal
    save_main_config(data)
    reset_adapter_cache()


def render_openems_connection_form(*, form_key: str = "ehal_openems_form") -> None:
    """Persist ehal.openems + backend=openems into config.json."""
    data = load_main_config()
    ehal = _ehal_block(data)
    openems = ehal.get("openems") if isinstance(ehal.get("openems"), dict) else {}
    st.caption("Zugangsdaten werden in `config.json` unter `ehal.openems` gespeichert.")
    with st.form(form_key):
        base_url = st.text_input(
            "OpenEMS Base-URL",
            value=str(openems.get("base_url") or "http://openems-edge:8084"),
        ).strip()
        username = st.text_input(
            "Benutzername",
            value=str(openems.get("username") or "x"),
        ).strip()
        password = st.text_input(
            "Passwort",
            value=str(openems.get("password") or "admin"),
            type="password",
        )
        ess = st.text_input(
            "ESS-Komponente",
            value=str(openems.get("ess_component") or "ess0"),
        ).strip() or "ess0"
        evcs = st.text_input(
            "EVCS-Komponente",
            value=str(openems.get("evcs_component") or "evcs0"),
        ).strip() or "evcs0"
        adapter_id = st.text_input(
            "adapter_id",
            value=str(ehal.get("adapter_id") or "openems-lab"),
        ).strip() or "openems-lab"
        submitted = st.form_submit_button("Speichern", type="primary")

    if not submitted:
        return
    if not base_url:
        st.error("Base-URL ist erforderlich.")
        return
    payload = dict(data)
    block = _ehal_block(payload)
    block["backend"] = BACKEND_OPENEMS
    block["adapter_id"] = adapter_id
    block["openems"] = {
        "base_url": base_url,
        "username": username or "x",
        "password": password or "admin",
        "ess_component": ess,
        "evcs_component": evcs,
    }
    payload["ehal"] = block
    save_main_config(payload)
    reset_adapter_cache()
    config.reinit_config(require_loxone_credentials=False)
    st.success("OpenEMS-Zugang gespeichert (`ehal.backend=openems`).")
    st.rerun()


def render_ha_connection_form(*, form_key: str = "ehal_ha_conn_form") -> None:
    """Persist ehal.ha base_url/token (+ backend=ha); mapping stays in ehal_ha_mapping."""
    data = load_main_config()
    ehal = _ehal_block(data)
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    st.caption("Zugangsdaten werden in `config.json` unter `ehal.ha` gespeichert.")
    with st.form(form_key):
        base_url = st.text_input(
            "Home Assistant URL",
            value=str(ha.get("base_url") or "http://homeassistant:8123"),
        ).strip()
        token = st.text_input(
            "Long-Lived Access Token",
            value=str(ha.get("token") or ""),
            type="password",
        ).strip()
        adapter_id = st.text_input(
            "adapter_id",
            value=str(ehal.get("adapter_id") or "ha-home"),
        ).strip() or "ha-home"
        submitted = st.form_submit_button("Speichern", type="primary")

    if not submitted:
        return
    if not base_url or not token:
        st.error("URL und Token sind erforderlich.")
        return
    payload = dict(data)
    block = _ehal_block(payload)
    block["backend"] = BACKEND_HA
    block["adapter_id"] = adapter_id
    existing_ha = dict(ha)
    existing_ha["base_url"] = base_url
    existing_ha["token"] = token
    if "entities" not in existing_ha:
        existing_ha["entities"] = {}
    if "sign" not in existing_ha:
        existing_ha["sign"] = {}
    block["ha"] = existing_ha
    payload["ehal"] = block
    save_main_config(payload)
    reset_adapter_cache()
    config.reinit_config(require_loxone_credentials=False)
    st.success("HA-Zugang gespeichert (`ehal.backend=ha`).")
    st.rerun()
