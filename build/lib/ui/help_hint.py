"""Kleine Hilfe-Icons per Popover (Streamlit ≥ 1.30)."""
from __future__ import annotations

import streamlit as st

_HELP_ICON = ":material/help_outline:"
_HELP_POPOVER_PREFIX = "help_hint__"


def _help_popover_key(key: str) -> str:
    return f"{_HELP_POPOVER_PREFIX}{key}"


def render_help_hint(body: str, *, key: str) -> None:
    """Zeigt ein kompaktes Hilfe-Icon — Inhalt erscheint im Popover."""
    with st.popover(
        "",
        icon=_HELP_ICON,
        type="tertiary",
        help="Hilfe anzeigen",
        key=_help_popover_key(key),
        width="content",
    ):
        st.markdown(body)


def render_title_with_help(title: str, help_text: str, *, key: str) -> None:
    """Überschrift mit Hilfe-Icon in einer Zeile."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"**{title}**")
        render_help_hint(help_text, key=key)


def render_page_title_with_help(
    title: str,
    help_text: str,
    *,
    key: str,
) -> None:
    """Seiten-Titel mit Hilfe-Icon."""
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        st.title(title)
        render_help_hint(help_text, key=key)


def render_status_with_help(
    message: str,
    help_text: str,
    *,
    key: str,
    prominent: bool = False,
) -> None:
    """Statuszeile sichtbar, Erklärung im Hilfe-Popover."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        if prominent:
            st.info(message)
        else:
            st.caption(message)
        render_help_hint(help_text, key=key)
