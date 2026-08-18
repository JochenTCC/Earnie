"""Smarthome-Backend: Loxone → Hausprofil import (2.4.n / 2.4.o)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations.loxone_connectivity import (
    loxone_env_configured,
    probe_loxone_http_access,
)
from integrations.loxone_greenfield_import import run_greenfield_import
from integrations.loxone_structure import LoxoneStructureError, fetch_loxapp3_json
from ui.doc_links import docs_blob_url
from ui.house_config_io import load_house_profiles, save_house_profiles

_SESSION_WIZARD = "greenfield_loxone_wizard"
_SESSION_DISMISSED = "greenfield_loxone_dismissed"
_SESSION_LAST_REPORT = "greenfield_loxone_last_report"
_SESSION_FLASH_OK = "greenfield_loxone_flash_ok"
_SESSION_ACCESS = "greenfield_loxone_access"

_SIGNALE_URL = docs_blob_url(
    "docs/referenz/loxone-signals.md",
    fragment="multiple-flex-consumers-naming-convention",
)
_LIBRARY_URL = docs_blob_url(
    "docs/referenz/loxone-signals.md",
    fragment="library-setup",
)

_CREDENTIALS_HINT = (
    "Loxone-Zugangsdaten fehlen oder der Miniserver ist nicht erreichbar. "
    "Bitte zuerst oben unter **Smarthome-Backend** eintragen und prüfen."
)
_IMPORT_HINT = (
    "Earnie kann die Verbraucher aus der Loxone Config importieren, wenn die "
    "Earnie-Templates verwendet wurden und für jeden Verbraucher ein "
    f"Zählerbaustein eingefügt wurde — siehe [Anleitung]({_LIBRARY_URL})."
)
_IMPORT_SAVED_FLASH = (
    "Loxone-Import gespeichert. Entities/Bindings sind gesetzt — "
    "Signal-Mapping auf **EHAL-Com** prüfen, angelegte Verbraucher "
    "im **Hauskonfigurator** prüfen und Parameter dort ergänzen."
)


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


def _show_onboarding_prompt() -> bool:
    """True when Erstsetup hint + dismiss button should appear next to Import."""
    from ui.setup_readiness import needs_planning_onboarding

    if not needs_planning_onboarding() or onboarding_dismissed():
        return False
    set_wizard_flag()
    return True


def _access_fingerprint(host: str, user: str, password: str) -> str:
    return f"{host}|{user}|{len(password)}"


def resolve_loxone_import_access(
    *,
    host: str,
    user: str,
    password: str,
    credentials_ok: bool,
    probe_fn=probe_loxone_http_access,
) -> tuple[bool, str | None]:
    """Return ``(button_enabled, hint_if_disabled)`` for Loxone-Import."""
    if not credentials_ok or not host or not user:
        return False, _CREDENTIALS_HINT
    ok, _detail = probe_fn(host=host, username=user, password=password)
    if ok:
        return True, None
    return False, _CREDENTIALS_HINT


def _loxone_import_access() -> tuple[bool, str | None]:
    """Cached Miniserver access check for the Import button."""
    host = str(config.get("LOXONE_IP") or "").strip()
    user = str(config.get("LOXONE_USER") or "").strip()
    password = str(config.get("LOXONE_PASS") or "")
    credentials_ok = loxone_env_configured()
    fp = _access_fingerprint(host, user, password)
    cached = st.session_state.get(_SESSION_ACCESS)
    if (
        isinstance(cached, tuple)
        and len(cached) == 3
        and cached[0] == fp
        and isinstance(cached[1], bool)
    ):
        enabled = bool(cached[1])
        return enabled, None if enabled else _CREDENTIALS_HINT
    enabled, hint = resolve_loxone_import_access(
        host=host,
        user=user,
        password=password,
        credentials_ok=credentials_ok,
    )
    st.session_state[_SESSION_ACCESS] = (fp, enabled, hint)
    return enabled, hint


def render_greenfield_import_section() -> None:
    """Loxone-Import control on Hauskonfigurator (above Verbraucher)."""
    show_onboarding = _show_onboarding_prompt()
    wizard = wizard_active()
    access_ok, access_hint = _loxone_import_access()

    st.subheader("Loxone-Import")
    st.caption(
        "Liest `LoxAPP3.json`, prüft `Earnie_*` per HTTP-Probe "
        "(inkl. Prefix+Slug, z. B. `Earnie_Verbraucher_Waschmaschine_Leistung`), "
        "legt typisierte Verbraucher an und merged EFM-Zähler. "
        f"[Namenskonvention]({_SIGNALE_URL})."
    )
    st.info(_IMPORT_HINT)
    if not access_ok and access_hint:
        st.warning(access_hint)

    if show_onboarding:
        import_col, dismiss_col = st.columns(2)
        with import_col:
            clicked = st.button(
                "Loxone-Import",
                key="hk_loxone_import_btn",
                type="primary" if wizard else "secondary",
                disabled=not access_ok,
            )
        with dismiss_col:
            if st.button("Nein — manuell fortfahren", key="hk_greenfield_no"):
                dismiss_onboarding()
                st.rerun()
    else:
        clicked = st.button(
            "Loxone-Import",
            key="hk_loxone_import_btn",
            type="primary" if wizard else "secondary",
            disabled=not access_ok,
        )
    if not clicked:
        if st.session_state.pop(_SESSION_FLASH_OK, None):
            st.success(_IMPORT_SAVED_FLASH)
        report = st.session_state.get(_SESSION_LAST_REPORT)
        if isinstance(report, dict):
            _show_report(report)
        return
    _run_import()


def _run_import() -> None:
    from runtime_store.ehal_setup import BACKEND_LOXONE
    from ui.ehal_connection import persist_ehal_backend

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
    persist_ehal_backend(BACKEND_LOXONE)
    house = load_house_profiles()
    with st.spinner("Loxone-Import (Probe + Merker + EFM)…"):
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
    profile_id = str(report.get("profile_id") or "").strip()
    if profile_id:
        from ui.house_config_profile_session import (
            _SESSION_SELECT_PENDING_KEY,
            _SESSION_SYNC_KEY,
        )

        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = None
    clear_wizard_flag()
    dismiss_onboarding()
    st.rerun()


def _show_report(report: dict[str, Any]) -> None:
    matched = len(report.get("matched_markers") or [])
    created = len(report.get("created_consumers") or [])
    plant = len(report.get("plant_fields") or [])
    efm = len(report.get("efm_created") or [])
    clocks = len(report.get("alarm_clock_bound") or [])
    missing = len(report.get("probed_missing") or [])
    st.caption(
        f"Treffer: {matched} Merker · {created} Verbraucher angelegt · "
        f"{plant} Plant-Felder · {efm} EFM-Verbraucher · "
        f"{clocks} AlarmClock→FertigUm · {missing} Probe-404"
    )
