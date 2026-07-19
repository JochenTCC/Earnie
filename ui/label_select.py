"""Selectbox options keyed by live Bezeichnung so Streamlit refreshes labels.

Streamlit tracks selectbox identity by visible option text. Using stable IDs with
``format_func`` leaves the closed dropdown stale after Bezeichnung changes.
Pass Bezeichnung strings as the options themselves instead.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

NEW_OPTION = "— neu —"


def entity_display_label(entity_map: dict[str, dict], entity_id: str) -> str:
    return str(entity_map.get(entity_id, {}).get("label") or entity_id)


def label_select_choices(
    entity_map: dict[str, dict],
    entity_ids: list[str],
    *,
    new_option: str | None = NEW_OPTION,
) -> tuple[list[str], dict[str, str]]:
    """Return (display options, display→id map)."""
    displays: list[str] = []
    id_by_display: dict[str, str] = {}
    if new_option is not None:
        displays.append(new_option)
        id_by_display[new_option] = new_option
    for entity_id in entity_ids:
        display = entity_display_label(entity_map, entity_id)
        if display in id_by_display:
            display = f"{display} ({entity_id})"
        displays.append(display)
        id_by_display[display] = entity_id
    return displays, id_by_display


def align_label_select_session(
    *,
    select_key: str,
    selected_id_key: str,
    entity_map: dict[str, dict],
    entity_ids: list[str],
    id_by_display: dict[str, str],
    new_option: str | None = NEW_OPTION,
) -> None:
    """Keep widget session value on the current Bezeichnung for the selected id."""
    current = st.session_state.get(select_key)
    if current is not None and str(current) in id_by_display:
        mapped = id_by_display[str(current)]
        if new_option is None or mapped != new_option:
            st.session_state[selected_id_key] = mapped
        return

    selected_id = st.session_state.get(selected_id_key)
    if selected_id in entity_ids:
        st.session_state[select_key] = entity_display_label(entity_map, str(selected_id))
        return
    if current is not None and str(current) in entity_ids:
        st.session_state[selected_id_key] = str(current)
        st.session_state[select_key] = entity_display_label(entity_map, str(current))


def refresh_label_select_display(
    *,
    select_key: str,
    selected_id: str | None,
    entity_map: dict[str, dict],
    entity_ids: list[str],
    id_by_display: dict[str, str],
    new_option: str | None = NEW_OPTION,
) -> None:
    """Rewrite stale widget text from ``selected_id`` without changing the id store.

    Use when the stable id must stay unchanged until after the selectbox (e.g. dirty
    switch guards in the scenario editor).
    """
    current = st.session_state.get(select_key)
    if current is not None and str(current) in id_by_display:
        return
    if new_option is not None and selected_id == new_option:
        st.session_state[select_key] = new_option
        return
    if selected_id in entity_ids:
        st.session_state[select_key] = entity_display_label(entity_map, str(selected_id))
        return
    if current is not None and str(current) in entity_ids:
        st.session_state[select_key] = entity_display_label(entity_map, str(current))


def resolve_label_select(
    selected_display: Any,
    id_by_display: dict[str, str],
) -> str:
    return id_by_display.get(str(selected_display), str(selected_display))
