"""Gemeinsame Hilfen für Szenario-Editor-Selectboxen und Entitäts-ID-Auflösung."""
from __future__ import annotations

import streamlit as st

NONE_LABEL = "— keine —"
EMPTY_PLACEHOLDER_PREFIX = "— noch keine"


def options_for_entities(
    items: list[dict],
    *,
    allow_none: bool = False,
) -> tuple[list[str], dict[str, str]]:
    labels: list[str] = []
    mapping: dict[str, str] = {}
    if allow_none:
        labels.append(NONE_LABEL)
        mapping[NONE_LABEL] = ""
    for item in items:
        label = f"{item.get('label', item['id'])} ({item['id']})"
        labels.append(label)
        mapping[label] = item["id"]
    return labels, mapping


def default_label_index(options: list[str], item_id: str | None) -> int:
    if not item_id or not options:
        return 0
    for index, opt in enumerate(options):
        if opt.endswith(f"({item_id})"):
            return index
    return 0


def lookup_entity_id(mapping: dict[str, str], pick: str | None) -> str:
    if pick is None:
        return ""
    return mapping.get(pick, "")


def render_entity_selectbox(
    label: str,
    items: list[dict],
    *,
    allow_none: bool = False,
    key: str,
    current_id: str | None,
) -> str | None:
    """Selectbox für Entitäten; bei leerer Liste deaktivierter Platzhalter, Rückgabe None."""
    labels, _mapping = options_for_entities(items, allow_none=allow_none)
    if not labels:
        placeholder = f"{EMPTY_PLACEHOLDER_PREFIX} {label.lower()} —"
        st.selectbox(label, options=[placeholder], disabled=True, key=key)
        return None
    return st.selectbox(
        label,
        options=labels,
        index=default_label_index(labels, current_id),
        key=key,
    )
