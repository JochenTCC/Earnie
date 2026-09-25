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


def render_anbindung_section(backend: str, *, form_key_prefix: str) -> None:
    """Credentials re-entry for the already-selected backend (SB Anbindung)."""
    from ui.setup_dotenv import render_loxone_credentials_form

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
        openems_default = default_adapter_id(BACKEND_OPENEMS)
        adapter_id = st.text_input(
            "adapter_id",
            value=resolve_adapter_id(ehal.get("adapter_id"), BACKEND_OPENEMS),
        ).strip() or openems_default
        submitted = st.form_submit_button("Speichern", type="primary")

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
    st.rerun()


def _ha_connection_defaults() -> dict[str, Any]:
    """Supervisor detection plus stored .env URL/token for the form defaults."""
    from integrations.ha_supervisor import (
        SUPERVISOR_CORE_BASE_URL,
        supervisor_proxy_available,
    )
    from runtime_store.dotenv_io import read_ha_credentials

    use_supervisor = supervisor_proxy_available()
    default_url = (
        SUPERVISOR_CORE_BASE_URL
        if use_supervisor
        else "http://homeassistant:8123"
    )
    stored_url, stored_token = read_ha_credentials()
    return {
        "use_supervisor": use_supervisor,
        "url": stored_url or default_url,
        "token": stored_token,
    }


def _render_ha_connection_captions(*, use_supervisor: bool) -> None:
    st.caption(
        "Zugangsdaten werden in `config/.env` gespeichert "
        "(`EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN`)."
    )
    if use_supervisor:
        st.caption(
            "Als Home-Assistant-Add-on: leerer Token nutzt den Supervisor-Proxy "
            "(`SUPERVISOR_TOKEN`) — kein manuelles Long-Lived Access Token nötig."
        )


def _render_ha_form_inputs(
    form_key: str,
    *,
    ehal: dict,
    defaults: dict[str, Any],
) -> tuple[str, str, str, bool]:
    """HA inputs; returns (base_url, token, adapter_id, submitted)."""
    with st.form(form_key):
        base_url = st.text_input(
            "Home Assistant URL",
            value=defaults["url"],
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
            value=defaults["token"],
            type="password",
            help=(
                "Optional im Add-on: leer lassen, um SUPERVISOR_TOKEN zu verwenden."
                if defaults["use_supervisor"]
                else None
            ),
        ).strip()
        ha_default = default_adapter_id(BACKEND_HA)
        adapter_id = st.text_input(
            "adapter_id",
            value=resolve_adapter_id(ehal.get("adapter_id"), BACKEND_HA),
        ).strip() or ha_default
        submitted = st.form_submit_button("Speichern", type="primary")
    return base_url, token, adapter_id, bool(submitted)


def _ha_submission_is_valid(base_url: str, token: str) -> bool:
    from integrations.ha_supervisor import resolve_ha_token

    if not base_url:
        st.error("URL ist erforderlich.")
        return False
    if not resolve_ha_token(token):
        st.error(
            "Token ist erforderlich "
            "(oder SUPERVISOR_TOKEN beim Betrieb als Home-Assistant-Add-on)."
        )
        return False
    return True


def _write_ha_credentials(base_url: str, token: str) -> bool:
    """Persist URL/token to config/.env; False when writing failed."""
    from integrations.ha_supervisor import resolve_ha_base_url
    from runtime_store.dotenv_io import write_ha_dotenv
    from runtime_store.dotenv_loader import load_app_dotenv

    # Prefer resolving empty URL via Supervisor defaults before persist when
    # the user left the field at the Supervisor Core proxy URL.
    resolved_url = resolve_ha_base_url(base_url) or base_url
    # Never persist SUPERVISOR_TOKEN — keep empty so runtime resolves it.
    try:
        write_ha_dotenv(resolved_url, token)
    except (OSError, PermissionError) as exc:
        st.error(f"Speichern der .env fehlgeschlagen: {exc}")
        return False
    load_app_dotenv(override=True)
    return True


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
    """Persist HA URL/token to .env (+ backend=ha); mapping stays in ehal_ha_mapping."""
    data = load_main_config()
    ehal = _ehal_block(data)
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    defaults = _ha_connection_defaults()
    _render_ha_connection_captions(use_supervisor=defaults["use_supervisor"])
    base_url, token, adapter_id, submitted = _render_ha_form_inputs(
        form_key, ehal=ehal, defaults=defaults
    )

    if not submitted:
        return
    if not _ha_submission_is_valid(base_url, token):
        return
    if not _write_ha_credentials(base_url, token):
        return
    _persist_ha_connection(data, ha, adapter_id=adapter_id)
    st.success("HA-Zugang gespeichert (`ehal.backend=ha`, Zugangsdaten in `.env`).")
    st.rerun()
