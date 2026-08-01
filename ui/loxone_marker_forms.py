"""Deprecated: plant ``loxone_blocks`` / Merker event-trigger editors.

Bindings are edited entity-centrically on EHAL-Com
(``ui/ehal_loxone_mapping.py``) and stored in ``house_profiles.json``.
Merker event-triggers were removed; use Loxone VO ``Earnie_Request_Optimize``
(Daemon-HTTP, ``system.ehal_loxone_http_port``, default 8541).
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
        "Merker-Event-Trigger sind entfernt. Für außerplanmäßige Optimierung nutzt "
        "Loxone Virtual Out **Earnie_Request_Optimize** den Daemon-HTTP-Port "
        "(`system.ehal_loxone_http_port`, Standard **8541**)."
    )


def render_marker_config_editors() -> None:
    """No-op stub — editors removed in 2.4.k / Request-Optimize cutover."""
    render_loxone_blocks_form()
    render_event_triggers_form()
