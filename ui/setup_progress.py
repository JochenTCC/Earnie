"""Hinweis zur Greenfield-Einrichtung in der Sidebar."""
from __future__ import annotations

import streamlit as st

from runtime_store.env_vars import is_explicit_offline
from runtime_store.dotenv_io import loxone_credentials_configured, loxone_setup_deferred
from ui.setup_dotenv import render_loxone_credentials_form
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


def should_show_loxone_sidebar() -> bool:
    """Sidebar wenn Zugang fehlt (deferred) oder Zugangsdaten hinterlegt sind."""
    if is_explicit_offline():
        return False
    if loxone_credentials_configured():
        return True
    return loxone_setup_deferred()


def render_deferred_loxone_sidebar() -> None:
    """Sidebar-Expander für Loxone-.env (unabhängig von Planungs-Hinweisen)."""
    if not should_show_loxone_sidebar():
        return

    credentials_ready = loxone_credentials_configured()
    expand = not credentials_ready
    with st.sidebar.expander("Loxone-Zugang (Live / Silent-Modus)", expanded=expand):
        if credentials_ready:
            st.success("Zugangsdaten hinterlegt.")
            st.caption(
                "Merker testen: **Echtzeit-Umgebung → Loxone-Kommunikation**."
            )
        else:
            st.caption(
                "Miniserver-Zugang erst für Live-Optimierung, Silent-Modus (Lesen) "
                "oder Merker-Test erforderlich — nicht für Planung/Backtesting."
            )
            render_loxone_credentials_form(form_key="loxone_sidebar_form")


def render_setup_progress_notice() -> None:
    """Zeigt fehlende Einrichtungsschritte, solange Navigation eingeschränkt ist."""
    if not needs_planning_onboarding():
        return
    if is_planning_ready():
        if is_betrieb_unlocked():
            return
        st.sidebar.success(
            "Planungs-Konfiguration vollständig — Analyse ist freigeschaltet. "
            "Betrieb folgt nach Loxone-Anbindung (Sidebar)."
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
        lines.append("**Echtzeit-Umgebung:**")
        lines.extend(f"- {item}" for item in runtime_missing)
    if not lines:
        missing = missing_planning_setup_items()
        if not missing:
            return
        lines = [f"- {item}" for item in missing]
    st.sidebar.info("Einrichtung unvollständig — noch offen:\n\n" + "\n".join(lines))
