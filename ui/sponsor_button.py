"""Sidebar button "Earnie unterstützen" (GitHub Sponsors) and its opt-out."""
from __future__ import annotations

import streamlit as st

from runtime_store.sponsoring import SPONSORS_URL, is_opted_out, set_opt_out

SPONSOR_BUTTON_LABEL = "Earnie unterstützen"
OPT_OUT_LABEL = "Unterstützen-Knopf ausblenden"
_OPT_OUT_KEY = "sponsor_opt_out_checkbox"


def render_sponsor_sidebar_button() -> None:
    """Link button to the Sponsors profile; hidden after opt-out."""
    if is_opted_out():
        return
    st.sidebar.link_button(
        SPONSOR_BUTTON_LABEL,
        SPONSORS_URL,
        help=(
            "Freiwillige Unterstützung über GitHub Sponsors. Earnie bleibt "
            "für alle gleich; es gibt dafür keine Gegenleistung."
        ),
        width="stretch",
    )


def _on_opt_out_change() -> None:
    set_opt_out(bool(st.session_state.get(_OPT_OUT_KEY)))


def render_sponsor_opt_out_checkbox() -> None:
    """Checkbox inside Info / About; the change is saved by the callback before the rerun."""
    if _OPT_OUT_KEY not in st.session_state:
        st.session_state[_OPT_OUT_KEY] = is_opted_out()
    st.checkbox(OPT_OUT_LABEL, key=_OPT_OUT_KEY, on_change=_on_opt_out_change)
