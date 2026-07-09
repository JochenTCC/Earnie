"""Hinweis zur Greenfield-Einrichtung in der Sidebar."""
from __future__ import annotations

import streamlit as st

from ui.setup_readiness import (
    is_betrieb_unlocked,
    is_house_config_ready,
    is_planning_ready,
    is_setup_navigation_restricted,
    missing_house_config_items,
    missing_planning_setup_items,
    missing_runtime_scenario_items,
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
    house_missing = missing_house_config_items()
    runtime_missing = missing_runtime_scenario_items()
    lines: list[str] = []
    if house_missing:
        lines.append("**Hauskonfigurator:**")
        lines.extend(f"- {item}" for item in house_missing)
    if is_house_config_ready() and runtime_missing:
        lines.append("**Szenarieneditor:**")
        lines.extend(f"- {item}" for item in runtime_missing)
    if not lines:
        missing = missing_planning_setup_items()
        if not missing:
            return
        lines = [f"- {item}" for item in missing]
    st.sidebar.info("Einrichtung unvollständig — noch offen:\n\n" + "\n".join(lines))
