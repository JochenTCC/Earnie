"""Deprecated: plant ``loxone_blocks`` / Merker event-trigger editors.

Loxone contract UI is the EHAL-Com **Signalliste** (``ui/ehal_signal_list.py``).
Merker event-triggers were removed; use Loxone VO ``Earnie_Request_Optimize``
(Daemon-HTTP, ``system.ehal_loxone_http_port``, default 8541).
"""
from __future__ import annotations

import streamlit as st


def render_loxone_blocks_form() -> None:
    st.info(
        "Loxone-Signale stehen unter **EHAL-Com → Signalliste**. "
        "Aktivierte Bindings liegen in `house_profiles.json` → `plant.ehal_bindings` "
        "(und Pattern B auf Verbrauchern / Batterien)."
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
