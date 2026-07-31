"""EHAL-Com: Greenfield Loxone import button (2.4.n P3)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations.loxone_greenfield_import import run_greenfield_import
from integrations.loxone_structure import LoxoneStructureError, fetch_loxapp3_json
from ui.doc_links import docs_blob_url
from ui.house_config_io import load_house_profiles, save_house_profiles

_SESSION_WIZARD = "greenfield_loxone_wizard"
_SESSION_DISMISSED = "greenfield_loxone_dismissed"
_SESSION_LAST_REPORT = "greenfield_loxone_last_report"
_SESSION_FLASH_OK = "greenfield_loxone_flash_ok"

_SIGNALE_URL = docs_blob_url(
    "docs/referenz/loxone-signale.md",
    fragment="mehrere-flex-verbraucher-namenskonvention",
)
_LIBRARY_URL = docs_blob_url("docs/einrichtung/loxone-earnie-library.md")


def wizard_active() -> bool:
    return bool(st.session_state.get(_SESSION_WIZARD))


def clear_wizard_flag() -> None:
    st.session_state.pop(_SESSION_WIZARD, None)


def set_wizard_flag() -> None:
    st.session_state[_SESSION_WIZARD] = True
    st.session_state.pop(_SESSION_DISMISSED, None)


def dismiss_onboarding() -> None:
    st.session_state[_SESSION_DISMISSED] = True
    st.session_state.pop(_SESSION_WIZARD, None)


def onboarding_dismissed() -> bool:
    return bool(st.session_state.get(_SESSION_DISMISSED))


def render_greenfield_import_section() -> None:
    """Primary Greenfield import control on EHAL-Com (backend Loxone)."""
    wizard = wizard_active()
    st.markdown("**Greenfield-Import** (Merker + EFM → Hausprofil / EHAL-Bindings)")
    st.caption(
        "Liest `LoxAPP3.json`, prüft `Earnie_*` per HTTP-Probe "
        "(inkl. Prefix+Slug, z. B. `Earnie_Verbraucher_Waschmaschine_Leistung`), "
        "legt typisierte Verbraucher an und merged EFM-Zähler. "
        f"Parameter danach im Hauskonfigurator. "
        f"[Library-Anleitung]({_LIBRARY_URL}) · "
        f"[Namenskonvention]({_SIGNALE_URL})."
    )
    if wizard:
        st.info(
            "Assistent aktiv: zuerst Library/Merker auf dem Miniserver "
            f"([Anleitung]({_LIBRARY_URL})), dann importieren — danach Mapping prüfen "
            "und Parameter im Hauskonfigurator setzen."
        )
    clicked = st.button(
        "Greenfield importieren",
        key="ehal_greenfield_import_btn",
        type="primary" if wizard else "secondary",
    )
    if not clicked:
        if st.session_state.pop(_SESSION_FLASH_OK, None):
            st.success(
                "Greenfield-Import gespeichert. Entities/Bindings sind gesetzt — "
                "Parameter im Hauskonfigurator ergänzen."
            )
        report = st.session_state.get(_SESSION_LAST_REPORT)
        if isinstance(report, dict):
            _show_report(report)
        return
    _run_import()


def _run_import() -> None:
    host = str(config.get("LOXONE_IP") or "").strip()
    user = str(config.get("LOXONE_USER") or "").strip()
    password = str(config.get("LOXONE_PASS") or "")
    if not host or not user:
        st.error("Loxone-Zugangsdaten fehlen (LOXONE_IP / LOXONE_USER in .env).")
        return
    try:
        doc = fetch_loxapp3_json(host=host, username=user, password=password)
    except LoxoneStructureError as exc:
        st.error(f"LoxAPP3 konnte nicht geladen werden: {exc}")
        return
    house = load_house_profiles()
    with st.spinner("Greenfield-Import (Probe + Merker + EFM)…"):
        result = run_greenfield_import(
            doc,
            house,
            probe_host=host,
            probe_username=user,
            probe_password=password,
        )
    save_house_profiles(result["house_doc"])
    report = result.get("report") or {}
    st.session_state[_SESSION_LAST_REPORT] = report
    st.session_state[_SESSION_FLASH_OK] = True
    clear_wizard_flag()
    st.rerun()


def _show_report(report: dict[str, Any]) -> None:
    matched = len(report.get("matched_markers") or [])
    created = len(report.get("created_consumers") or [])
    plant = len(report.get("plant_fields") or [])
    efm = len(report.get("efm_created") or [])
    missing = len(report.get("probed_missing") or [])
    st.caption(
        f"Treffer: {matched} Merker · {created} Verbraucher angelegt · "
        f"{plant} Plant-Felder · {efm} EFM-Verbraucher · "
        f"{missing} Probe-404"
    )
