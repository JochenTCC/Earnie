"""Kleine Hilfe-„?“ per Popover (Streamlit ≥ 1.30)."""
from __future__ import annotations

import streamlit as st


def render_help_hint(body: str, *, key: str, label: str = "?") -> None:
    """Zeigt ein kompaktes ? — Inhalt erscheint im Popover."""
    with st.popover(label, help="Hilfe anzeigen", key=key):
        st.markdown(body)


def render_title_with_help(title: str, help_text: str, *, key: str) -> None:
    """Überschrift mit ?-Popover in einer Zeile."""
    col_title, col_help = st.columns([11, 1])
    with col_title:
        st.markdown(f"**{title}**")
    with col_help:
        render_help_hint(help_text, key=key)


def render_page_title_with_help(
    title: str,
    help_text: str,
    *,
    key: str,
    version: str | None = None,
) -> None:
    """Seiten-Titel mit optionaler Versions-Caption und ?-Popover (Scope nur im ?)."""
    col_title, col_version, col_help = st.columns([8, 2, 1], vertical_alignment="bottom")
    with col_title:
        st.title(title)
    with col_version:
        if version:
            st.caption(f"Version {version}")
    with col_help:
        render_help_hint(help_text, key=key)


def render_status_with_help(
    message: str,
    help_text: str,
    *,
    key: str,
    prominent: bool = False,
) -> None:
    """Statuszeile sichtbar, Erklärung im ?-Popover."""
    if prominent:
        col_status, col_help = st.columns([11, 1], vertical_alignment="center")
        with col_status:
            st.info(message)
        with col_help:
            render_help_hint(help_text, key=key)
        return
    col_status, col_help = st.columns([11, 1], vertical_alignment="center")
    with col_status:
        st.caption(message)
    with col_help:
        render_help_hint(help_text, key=key)
