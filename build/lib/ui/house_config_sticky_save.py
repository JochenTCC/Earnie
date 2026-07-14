"""Sticky-Speichern-Leiste für lange Hauskonfigurator-Tabs."""
from __future__ import annotations

import streamlit as st

_STICKY_SAVE_CSS = """
<style>
div[data-testid="stVerticalBlockBorderWrapper"]:has(.house-config-sticky-save) {
    position: sticky;
    top: 3.25rem;
    z-index: 30;
    background: var(--background-color, #ffffff);
    padding: 0.25rem 0 0.5rem 0;
    border-bottom: 1px solid rgba(128, 128, 128, 0.25);
    margin-bottom: 0.5rem;
}
</style>
"""


def ensure_sticky_save_css() -> None:
    if st.session_state.get("_house_config_sticky_save_css"):
        return
    st.markdown(_STICKY_SAVE_CSS, unsafe_allow_html=True)
    st.session_state["_house_config_sticky_save_css"] = True


def sticky_save_bar() -> None:
    """Markiert die nächste Zeile als sticky Speichern-Leiste."""
    ensure_sticky_save_css()
    st.markdown('<div class="house-config-sticky-save"></div>', unsafe_allow_html=True)
