"""UsagePing P3 — German consent dialog + settings (Nutzungsstatistik)."""
from __future__ import annotations

import json
import logging

import streamlit as st

from runtime_store.usage_ping import (
    is_kill_switch_off,
    load_state,
    note_explorer_activated,
    preview_payload,
    set_consent,
)

logger = logging.getLogger(__name__)

_SESSION_DIALOG_CHOICE = "usage_ping_dialog_choice"
_SESSION_EXPLORER_ACTIVATED = "usage_ping_explorer_activated"

_DIALOG_INTRO = (
    "Um die Qualität von Earnie permanent zu verbessern, kann Earnie anonym "
    "melden, dass diese Installation aktiv ist (Versionszähler). Es werden "
    "**keine** Preise, Orte, Gerätenamen oder Konfigurationsinhalte gesendet. "
    "Im Live-Betrieb kommt eine grobe Größenkennzahl der Anlage hinzu "
    "(Earnie-Points, nur die Summe). "
    "Die Meldung ist **freiwillig**, jederzeit widerrufbar und hat **keinen "
    "Einfluss** auf die Optimierung."
)

_POINTS_EXPLANATION = (
    "`points` ist die Summe der **Earnie-Points** der Live-Anlage (grobe "
    "Größenkennzahl aus PV, Speicher, Wallboxen, Wärmepumpen / Klimaanlagen und "
    "flexiblen Großverbrauchern), `points_v` die Version der Berechnungsregel. "
    "Beide Felder erscheinen erst im Live-Betrieb und enthalten keine "
    "Konfigurationsinhalte."
)


def consent_is_unset() -> bool:
    return str(load_state().get("consent") or "unset") == "unset"


def _payload_json() -> str:
    return json.dumps(preview_payload(), indent=2, ensure_ascii=False)


def _render_payload_preview() -> None:
    try:
        st.code(_payload_json(), language="json")
    except ValueError as exc:
        st.error(f"Vorschau nicht möglich (Zustand in runtime/usage_ping.json prüfen): {exc}")


def _apply_consent(value: str) -> bool:
    try:
        set_consent(value)  # type: ignore[arg-type]
        return True
    except Exception as exc:
        logger.warning("usage_ping: consent update failed: %s", exc)
        st.error(f"Nutzungsstatistik konnte nicht gespeichert werden: {exc}")
        return False


@st.dialog("Nutzungsstatistik")
def _consent_dialog() -> None:
    st.markdown(_DIALOG_INTRO)
    st.caption(
        "Vorschau der gesendeten Felder "
        "(die Installations-ID entsteht erst bei Zustimmung):"
    )
    st.code(_payload_json(), language="json")
    col_yes, col_no, col_cancel = st.columns(3)
    with col_yes:
        if st.button("Zustimmen", type="primary", key="usage_ping_dialog_yes"):
            if _apply_consent("on"):
                st.session_state[_SESSION_DIALOG_CHOICE] = "answered"
                st.rerun()
    with col_no:
        if st.button("Ablehnen", key="usage_ping_dialog_no"):
            if _apply_consent("off"):
                st.session_state[_SESSION_DIALOG_CHOICE] = "answered"
                st.rerun()
    with col_cancel:
        if st.button("Abbrechen", key="usage_ping_dialog_cancel"):
            st.session_state[_SESSION_DIALOG_CHOICE] = "cancel"
            st.rerun()


def maybe_prompt_consent_on_explorer() -> None:
    """On Szenario-Explorer open: consent dialog if unset; always mark explorer.

    Idempotent per session for the activation milestone. Abbrechen leaves consent
    ``unset`` and does not record explorer activation this visit. Stage stays
    ``explorer`` (live comes later from a successful live cycle).
    """
    if is_kill_switch_off():
        return

    choice = st.session_state.pop(_SESSION_DIALOG_CHOICE, None)
    if choice == "cancel":
        return

    if choice == "answered" or not consent_is_unset():
        if not st.session_state.get(_SESSION_EXPLORER_ACTIVATED):
            note_explorer_activated()
            st.session_state[_SESSION_EXPLORER_ACTIVATED] = True
        return

    _consent_dialog()


def maybe_prompt_consent_on_editor() -> None:
    """Fallback when ``scenario_explorer`` is not in ``EARNIE_UI_MODES``.

    Szenarienkonfigurator still records the explorer milestone and may ask for
    opt-in so installs without the SE page are not skipped. When SE is enabled,
    the Szenario-Explorer page owns the prompt instead.
    """
    from ui.mode_selector import get_enabled_ui_mode_keys

    if "scenario_explorer" in get_enabled_ui_mode_keys():
        return
    maybe_prompt_consent_on_explorer()


def render_usage_ping_settings() -> None:
    """Toggle + payload expander on Optimierer-Dienst."""
    st.subheader("Nutzungsstatistik")
    kill = is_kill_switch_off()
    state = load_state()
    consent = str(state.get("consent") or "unset")
    if kill:
        st.caption(
            "Kill-Switch `EARNIE_USAGE_PING=off` ist aktiv — es wird nichts gesendet, "
            "auch wenn die Zustimmung eingeschaltet ist."
        )
    else:
        st.caption(
            "Optionaler anonymer Zähler aktiver Installationen — hilft, Earnie "
            "weiterzuentwickeln. Zustand in `runtime/usage_ping.json`."
        )

    enabled = consent == "on"
    toggled = st.toggle(
        "Anonyme Nutzungsstatistik senden",
        value=enabled,
        disabled=kill,
        key="usage_ping_settings_toggle",
        help=(
            "Bei Zustimmung sendet Earnie täglich ein anonymes JSON-Paket "
            "ohne persönliche Daten — wenn die Installation aktiv ist oder "
            "Szenarien erstellt wurden."
        ),
    )
    if not kill and toggled != enabled:
        if _apply_consent("on" if toggled else "off"):
            st.rerun()

    with st.expander("Was wird gesendet?", expanded=False):
        st.caption(
            "Exakte Feldliste. Die Installations-ID wird erst bei Zustimmung "
            "zufällig erzeugt."
        )
        _render_payload_preview()
        st.caption(_POINTS_EXPLANATION)
