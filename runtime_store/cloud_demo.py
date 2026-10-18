"""Streamlit Community Cloud: per-session empty Greenfield workspace."""
from __future__ import annotations

import os
import tempfile

from runtime_store.env_vars import is_truthy

SESSION_ENV_KEY = "_earnie_cloud_env_root"
SESSION_INTRO_DISMISSED_KEY = "_earnie_cloud_intro_dismissed"

# Test hook when Streamlit session_state is unavailable.
_test_session_env_root: str | None = None


def is_cloud_demo() -> bool:
    """True when EARNIE_CLOUD_DEMO is ``1``."""
    return is_truthy("CLOUD_DEMO")


def set_session_env_root_for_tests(root: str | None) -> None:
    """Override session env root for unit tests (no Streamlit)."""
    global _test_session_env_root
    _test_session_env_root = root


def get_session_env_root() -> str | None:
    """Absolute per-session env root, or None when not in a cloud demo session."""
    if _test_session_env_root:
        return _test_session_env_root
    # CLI / workers: never touch Streamlit session_state (avoids ScriptRunContext spam).
    if not is_cloud_demo():
        return None
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            get_script_run_ctx,
        )

        if get_script_run_ctx(suppress_warning=True) is None:
            return None
        import streamlit as st

        root = st.session_state.get(SESSION_ENV_KEY)
    except Exception:
        return None
    if isinstance(root, str) and root.strip():
        return root.strip()
    return None


def ensure_cloud_session_env() -> str | None:
    """
    Create or reuse a temp env root for the current Streamlit session.

    No-op when cloud demo is off. Does not set process-wide EARNIE_ENV_PATH.
    """
    if not is_cloud_demo():
        return None
    existing = get_session_env_root()
    if existing and os.path.isdir(existing):
        return existing

    root = tempfile.mkdtemp(prefix="earnie_cloud_")
    os.makedirs(os.path.join(root, "config"), exist_ok=True)
    os.makedirs(os.path.join(root, "runtime"), exist_ok=True)

    import streamlit as st

    st.session_state[SESSION_ENV_KEY] = root
    return root


def render_cloud_demo_intro() -> None:
    """One-time German welcome for empty Community Cloud Greenfield sessions."""
    if not is_cloud_demo():
        return
    import streamlit as st

    from ui.info_sidebar import MANUAL_URL

    if st.session_state.get(SESSION_INTRO_DISMISSED_KEY):
        return

    st.info(
        "**Willkommen beim Earnie Online Szenario-Explorer**\n\n"
        "Diese Session startet mit einer **leeren** Hauskonfiguration.\n"
        "Legen Sie zuerst im **Hauskonfigurator** Profil, Batterie und optional PV an."
        "Im Hausprofil können Sie (und sollten sie auch) beliebig viele Verbraucher anlegen mit dem typischen Nutzungsverhalten:\n"
        "- Haus Wärme: Wenn Sie Ihr Haus mit einer Wärmepumpe heizen\n"
        "- E-Auto: Für Ihr E-Auto\n"
        "- Temperatur: Für Pool oder andere beheizbare Geräte\n"
        "- Allgemein: Für sonstige Geräte\n\n"
        "Danach können Sie im **Szenarienkonfigurator** die Komponeneten zu Szenarien kombinieren - mit verschiedenen Tarifen\n"
        "Im **Szenarien-Explorer** können Sie die Szenarien testen und optimieren.\n\n"
        "Ihre Eingaben gelten nur für **diese Browser-Sitzung** und werden nicht "
        "mit anderen Besuchern geteilt. Sie können die Daten mit **Konfiguration Speichern / laden** lokal sichern und zu einem späteren Zeitpunkt hier wieder verwenden.\n\n"
        f"Weitere Informationen erhalten Sie im "
        f"[Benutzer-Handbuch]({MANUAL_URL}). "
        "Der Link ist auch unter **Info** zu finden."
    )
    if st.button("Verstanden", key="earnie_cloud_intro_dismiss"):
        st.session_state[SESSION_INTRO_DISMISSED_KEY] = True
        st.rerun()
