"""Smarthome-Backend (SB): discover, select, and configure the live-environment hub.

Runs both as a normal nav page (Daemon Control → Smarthome-Backend) and as the
blocking first-run screen (``ui.setup_dotenv.render_ehal_setup_page``) once
planning is complete and no backend is configured yet — same implementation,
one place to pick/verify a backend. See docs/spec/smarthome-backend-page.md.
"""
from __future__ import annotations

import streamlit as st

from integrations.integration_scanner import DiscoveredBackend, scan_for_backends
from runtime_store.ehal_setup import (
    BACKEND_HA,
    BACKEND_LOXONE,
    BACKEND_OPENEMS,
    active_ehal_backend,
    backend_label,
)
from runtime_store.install_context import install_context_target_kinds
from ui.ehal_connection import (
    persist_ehal_backend,
    render_anbindung_section,
    render_ha_connection_form,
    render_openems_connection_form,
)
from ui.help_hint import render_page_title_with_help
from ui.setup_dotenv import render_loxone_credentials_form, render_loxone_verify_results
from ui.setup_readiness import is_sb_configured

_SB_HELP = (
    "Wählt und verbindet die Smarthome-Steuerung (Loxone, Home Assistant oder "
    "OpenEMS) für den Live-Betrieb. Ohne Backend bleiben EHAL-Com, "
    "Optimierer-Dienst und der automatische Verbraucher-/EHAL-Import deaktiviert."
)

_KIND_TO_BACKEND = {
    "loxone": BACKEND_LOXONE,
    "home_assistant": BACKEND_HA,
    "openems": BACKEND_OPENEMS,
}

_SESSION_RESULTS = "sb_scan_results"
_SESSION_RAN_ACTIVE = "sb_ran_active_scan"
_SESSION_CHOSEN_BACKEND = "sb_chosen_backend"


def _run_scan(*, active: bool) -> list[DiscoveredBackend]:
    """Targeted scan first (install context); widen to full passive if empty."""
    if active:
        return scan_for_backends("full_active")
    kinds = install_context_target_kinds()
    mode = "targeted" if kinds else "full_passive"
    results = scan_for_backends(mode, only_kinds=kinds)
    if not results and mode == "targeted":
        results = scan_for_backends("full_passive")
    return results


def _describe_hit(hit: DiscoveredBackend) -> str:
    detail = f"`{hit.host}`"
    if hit.port:
        detail += f":{hit.port}"
    if hit.name:
        detail += f" — {hit.name}"
    return detail


def _render_backend_import_section(backend: str) -> None:
    """Automated consumer/EHAL import for the connected backend (Loxone today)."""
    if backend == BACKEND_LOXONE:
        from ui.ehal_greenfield_import import render_greenfield_import_section

        render_greenfield_import_section()
    else:
        st.caption(
            "Automatischer Verbraucher-/EHAL-Import ist für "
            f"{backend_label(backend)} noch nicht verfügbar."
        )


def _render_configured_summary() -> None:
    backend = active_ehal_backend()
    st.success(f"Smarthome-Backend verbunden: **{backend_label(backend)}**")
    st.caption("EHAL-Com und Optimierer-Dienst sind freigeschaltet.")
    render_anbindung_section(backend, form_key_prefix="sb_anbindung")
    with st.expander("Backend ändern", expanded=False):
        _render_discovery_flow()
    _render_backend_import_section(backend)


def _select_hit(hit: DiscoveredBackend) -> None:
    st.session_state[_SESSION_CHOSEN_BACKEND] = _KIND_TO_BACKEND[hit.kind]
    st.rerun()


def _render_scan_results(results: list[DiscoveredBackend]) -> None:
    if not results:
        st.warning(
            "Kein Smarthome-Backend gefunden. Bis zur Auswahl bleiben der "
            "automatische Verbraucher-/EHAL-Import sowie EHAL-Com und "
            "Optimierer-Dienst deaktiviert."
        )
        return
    if len(results) == 1:
        hit = results[0]
        st.info(f"Gefunden: **{backend_label(_KIND_TO_BACKEND[hit.kind])}** ({_describe_hit(hit)})")
        if st.button("Dieses Backend verwenden", key="sb_use_single_hit"):
            _select_hit(hit)
        return

    st.info(f"{len(results)} mögliche Backends gefunden — bitte auswählen:")
    labels = [f"{backend_label(_KIND_TO_BACKEND[h.kind])} ({_describe_hit(h)})" for h in results]
    choice = st.radio(
        "Gefundene Backends",
        labels,
        key="sb_multi_hit_choice",
        label_visibility="collapsed",
    )
    if st.button("Ausgewähltes Backend verwenden", key="sb_use_multi_hit"):
        _select_hit(results[labels.index(choice)])


def _render_manual_selection() -> None:
    st.markdown("**Manuelle Auswahl**")
    options = (BACKEND_LOXONE, BACKEND_HA, BACKEND_OPENEMS)
    labels = [backend_label(b) for b in options]
    choice = st.selectbox(
        "Smarthome-Backend",
        labels,
        key="sb_manual_backend_select",
        label_visibility="collapsed",
    )
    if st.button("Weiter", key="sb_manual_backend_confirm"):
        st.session_state[_SESSION_CHOSEN_BACKEND] = options[labels.index(choice)]
        st.rerun()


def _render_credentials_step(backend: str) -> None:
    st.markdown(f"**Zugangsdaten: {backend_label(backend)}**")
    if backend == BACKEND_LOXONE:
        # render_loxone_credentials_form alone doesn't set ehal.backend (loxone is
        # only the implicit default) — make a switch away from HA/OpenEMS explicit.
        persist_ehal_backend(BACKEND_LOXONE)
        render_loxone_credentials_form(form_key="sb_loxone_form")
        render_loxone_verify_results(button_key="sb_loxone_verify_button")
    elif backend == BACKEND_HA:
        render_ha_connection_form(form_key="sb_ha_form")
    elif backend == BACKEND_OPENEMS:
        render_openems_connection_form(form_key="sb_openems_form")
    if st.button("Andere Auswahl", key="sb_credentials_back"):
        st.session_state.pop(_SESSION_CHOSEN_BACKEND, None)
        st.rerun()


def _render_discovery_flow() -> None:
    chosen = st.session_state.get(_SESSION_CHOSEN_BACKEND)
    if chosen:
        _render_credentials_step(chosen)
        return

    if _SESSION_RESULTS not in st.session_state:
        with st.spinner("Suche nach Loxone / Home Assistant im Netzwerk…"):
            st.session_state[_SESSION_RESULTS] = _run_scan(active=False)

    results = st.session_state[_SESSION_RESULTS]
    _render_scan_results(results)

    if not results and not st.session_state.get(_SESSION_RAN_ACTIVE):
        st.caption(
            "Zusätzlich per aktivem Portscan nach OpenEMS suchen? Kann im "
            "Heimnetz Firewall-/IDS-Warnungen auslösen (z. B. UniFi)."
        )
        if st.button("Erweiterte Suche (inkl. OpenEMS-Portscan)", key="sb_active_scan_button"):
            with st.spinner("Erweiterte Suche inkl. OpenEMS-Portscan…"):
                st.session_state[_SESSION_RESULTS] = _run_scan(active=True)
            st.session_state[_SESSION_RAN_ACTIVE] = True
            st.rerun()

    if st.button("Neu scannen", key="sb_rescan_button"):
        st.session_state.pop(_SESSION_RESULTS, None)
        st.session_state.pop(_SESSION_RAN_ACTIVE, None)
        st.rerun()

    _render_manual_selection()


def render() -> None:
    render_page_title_with_help(
        "📡 Smarthome-Backend",
        _SB_HELP,
        key="smarthome_backend_help",
        page_docs_key="smarthome-backend",
    )
    if is_sb_configured():
        _render_configured_summary()
        return
    _render_discovery_flow()
