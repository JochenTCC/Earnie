"""Deprecated: plant ``loxone_blocks`` / ``system.event_triggers`` editors (2.4.k).

Bindings and event triggers are edited entity-centrically on EHAL-Com
(``ui/ehal_loxone_mapping.py``) and stored in ``house_profiles.json``.
"""
from __future__ import annotations

import streamlit as st


def render_loxone_blocks_form() -> None:
    st.info(
        "Anlagen-Merker werden unter **Loxone Struktur → EHAL Mapping** "
        "(Entity „Anlage“) gepflegt und in `house_profiles.json` → `plant.ehal_bindings` gespeichert."
    )


def render_event_triggers_form() -> None:
    st.info(
        "Event-Trigger liegen an Plant-/Verbraucher-Entities "
        "(`event_triggers` in `house_profiles.json`), nicht mehr unter `system.event_triggers`."
    )


def render_marker_config_editors() -> None:
    """No-op stub — editors removed in 2.4.k."""
    render_loxone_blocks_form()
    render_event_triggers_form()
