"""Hinweis zur Greenfield-Einrichtung in der Sidebar."""
from __future__ import annotations

import streamlit as st

from ui.setup_readiness import (
    is_betrieb_unlocked,
    is_planning_ready,
    is_setup_navigation_restricted,
    missing_planning_setup_items,
    needs_planning_onboarding,
)


def render_setup_progress_notice() -> None:
    """Zeigt fehlende Einrichtungsschritte, solange Navigation eingeschränkt ist."""
    if not needs_planning_onboarding():
        return
    if is_planning_ready():
        if is_betrieb_unlocked():
            return
        st.sidebar.success(
            "Planungs-Konfiguration vollständig — Analyse ist freigeschaltet. "
            "Betrieb folgt nach Loxone-Anbindung."
        )
        return
    if not is_setup_navigation_restricted():
        return
    missing = missing_planning_setup_items()
    if not missing:
        return
    st.sidebar.info(
        "Einrichtung unvollständig — noch offen:\n\n"
        + "\n".join(f"- {item}" for item in missing)
    )
