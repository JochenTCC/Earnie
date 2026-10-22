"""EHAL connection forms (Loxone/HA/OpenEMS) — backend persistence and credentials."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations.ehal_live import reset_adapter_cache
from runtime_store.ehal_setup import (
    BACKEND_HA,
    BACKEND_LOXONE,
    BACKEND_OPENEMS,
    backend_label,
    default_adapter_id,
    normalize_backend,
    resolve_adapter_id,
)
from ui.house_config_io import load_main_config, save_main_config


def _ehal_block(data: dict) -> dict[str, Any]:
    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    return dict(ehal)


def render_anbindung_section(
    backend: str,
    *,
    form_key_prefix: str,
    show_heading: bool = True,
) -> None:
    """Credentials re-entry for the already-selected backend (SB Anbindung)."""
    from ui.setup_dotenv import render_loxone_credentials_form

    if show_heading:
        st.subheader("Anbindung")
    st.caption(
        f"Backend: **{backend_label(backend)}** — Auswahl/Wechsel unter "
        "**Backend ändern**. Zugangsdaten können hier erneut geprüft werden."
    )
    if backend == BACKEND_LOXONE:
        render_loxone_credentials_form(form_key=f"{form_key_prefix}_loxone_form")
    elif backend == BACKEND_HA:
        render_ha_connection_form(form_key=f"{form_key_prefix}_ha_form")
    elif backend == BACKEND_OPENEMS:
        render_openems_connection_form(form_key=f"{form_key_prefix}_openems_form")


def persist_ehal_backend(backend: str) -> None:
    """Write ehal.backend (+ matching default adapter_id) and reload runtime config."""
    resolved = normalize_backend(backend)
    data = load_main_config()
    ehal = _ehal_block(data)
    if resolved == BACKEND_LOXONE:
        ehal["backend"] = "loxone"
    else:
        ehal["backend"] = resolved
    ehal["adapter_id"] = resolve_adapter_id(ehal.get("adapter_id"), resolved)
    data["ehal"] = ehal
    save_main_config(data)
    reset_adapter_cache()


def _render_openems_form_inputs(
    form_key: str,
    ehal: dict,
    openems: dict,
) -> tuple[dict[str, str], bool]:
    """OpenEMS credential inputs; returns (values, submitted)."""
    with st.form(form_key):
        base_url = st.text_input(
            "OpenEMS Base-URL",
            key=f"{form_key}_base_url",
            value=str(openems.get("base_url") or "http://openems-edge:8084"),
            help=(
                "Vollständige Base-URL inkl. Port, z. B. http://openems-edge:8084 "
                "(Standard-Port 8084)."
            ),
        ).strip()
        st.caption(
            "HTTP-Port weicht vom Standard ab? Port in der URL angeben "
            "(z. B. `http://openems-edge:8085`)."
        )
        username = st.text_input(
            "Benutzername",
            key=f"{form_key}_username",
            value=str(openems.get("username") or "x"),
        ).strip()
        password = st.text_input(
            "Passwort",
            key=f"{form_key}_password",
            value=str(openems.get("password") or "admin"),
            type="password",
        )
        ess = st.text_input(
            "ESS-Komponente",
            key=f"{form_key}_ess_component",
            value=str(openems.get("ess_component") or "ess0"),
        ).strip() or "ess0"
        evcs = st.text_input(
            "EVCS-Komponente",
            key=f"{form_key}_evcs_component",
            value=str(openems.get("evcs_component") or "evcs0"),
        ).strip() or "evcs0"
        openems_default = default_adapter_id(BACKEND_OPENEMS)
        adapter_id = st.text_input(
            "adapter_id",
            key=f"{form_key}_adapter_id",
            value=resolve_adapter_id(ehal.get("adapter_id"), BACKEND_OPENEMS),
        ).strip() or openems_default
        submitted = st.form_submit_button(
            "Speichern", type="primary", key=f"{form_key}_submit"
        )

    values = {
        "base_url": base_url,
        "username": username,
        "password": password,
        "ess_component": ess,
        "evcs_component": evcs,
        "adapter_id": adapter_id,
    }
    return values, bool(submitted)


def _persist_openems_connection(data: dict, values: dict[str, str]) -> None:
    payload = dict(data)
    block = _ehal_block(payload)
    block["backend"] = BACKEND_OPENEMS
    block["adapter_id"] = values["adapter_id"]
    block["openems"] = {
        "base_url": values["base_url"],
        "username": values["username"] or "x",
        "password": values["password"] or "admin",
        "ess_component": values["ess_component"],
        "evcs_component": values["evcs_component"],
    }
    payload["ehal"] = block
    save_main_config(payload)
    reset_adapter_cache()
    config.reinit_config(require_loxone_credentials=False)


def render_openems_connection_form(*, form_key: str = "ehal_openems_form") -> None:
    """Persist ehal.openems + backend=openems into config.json."""
    data = load_main_config()
    ehal = _ehal_block(data)
    openems = ehal.get("openems") if isinstance(ehal.get("openems"), dict) else {}
    st.caption("Zugangsdaten werden in `config.json` unter `ehal.openems` gespeichert.")
    values, submitted = _render_openems_form_inputs(form_key, ehal, openems)

    if not submitted:
        return
    if not values["base_url"]:
        st.error("Base-URL ist erforderlich.")
        return
    _persist_openems_connection(data, values)
    st.success("OpenEMS-Zugang gespeichert (`ehal.backend=openems`).")
    st.session_state.pop("sb_chosen_backend", None)
    st.rerun()


def _persist_ha_connection(data: dict, ha: dict, *, adapter_id: str) -> None:
    payload = dict(data)
    block = _ehal_block(payload)
    block["backend"] = BACKEND_HA
    block["adapter_id"] = adapter_id
    existing_ha = dict(ha)
    existing_ha.pop("base_url", None)
    existing_ha.pop("token", None)
    if "entities" not in existing_ha:
        existing_ha["entities"] = {}
    if "sign" not in existing_ha:
        existing_ha["sign"] = {}
    block["ha"] = existing_ha
    payload["ehal"] = block
    save_main_config(payload)
    reset_adapter_cache()
    config.reinit_config(require_loxone_credentials=False)


def render_ha_connection_form(*, form_key: str = "ehal_ha_conn_form") -> None:
    """Select Home Assistant (``ehal.backend=ha``); bindings via Signal list.

    Push-only: Home Assistant calls Earnie, so no HA URL / token is asked for.
    """
    data = load_main_config()
    ehal = _ehal_block(data)
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    st.caption(
        "Home Assistant ruft Earnie auf (Telemetrie-Push und `status.json`, Port 8541) — "
        "Earnie braucht dafür **keine** HA-URL und kein Token. Nächster Schritt: "
        "**EHAL-Com → HA Push-Carrier → YAML-Paket** laden und in Home Assistant einbinden."
    )
    with st.form(form_key):
        adapter_id = st.text_input(
            "adapter_id",
            key=f"{form_key}_adapter_id",
            value=resolve_adapter_id(ehal.get("adapter_id"), BACKEND_HA),
        ).strip() or default_adapter_id(BACKEND_HA)
        submitted = st.form_submit_button(
            "Speichern", type="primary", key=f"{form_key}_submit"
        )
    if not submitted:
        return
    _persist_ha_connection(data, ha, adapter_id=adapter_id)
    st.success("Home Assistant gewählt (`ehal.backend=ha`).")
    st.session_state.pop("sb_chosen_backend", None)
    st.rerun()
