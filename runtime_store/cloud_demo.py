"""Streamlit Community Cloud: per-session empty Greenfield workspace."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from urllib.parse import quote

from runtime_store.env_vars import is_truthy

SESSION_ENV_KEY = "_earnie_cloud_env_root"
SESSION_INTRO_DISMISSED_KEY = "_earnie_cloud_intro_dismissed"
SESSION_SE_SIM_STARTED_KEY = "_earnie_cloud_se_sim_started"
SESSION_SE_FEEDBACK_DISMISSED_KEY = "_earnie_cloud_se_feedback_dismissed"

FEEDBACK_EMAIL = "jochen@techcreacon.com"
_FEEDBACK_SUBJECT = "Earnie Cloud-Demo — Feedback Szenario-Explorer"

# Test hook when Streamlit session_state is unavailable.
_test_session_env_root: str | None = None


def is_cloud_demo() -> bool:
    """True when EARNIE_CLOUD_DEMO / ENERGY_OPTIMIZER_CLOUD_DEMO is ``1``."""
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
        "Danach können Sie im **Szenarien-Editor** die Komponeneten zu Szenarien kombinieren - mit verschiedenen Tarifen\n"
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


def mark_cloud_demo_se_simulation_started() -> None:
    """Remember that this cloud-demo session started a Szenario-Explorer run."""
    if not is_cloud_demo():
        return
    import streamlit as st

    st.session_state[SESSION_SE_SIM_STARTED_KEY] = True


def build_cloud_demo_feedback_mailto(
    message: str = "",
    *,
    attach_config: bool = False,
) -> str:
    """Build mailto URL for cloud-demo SE feedback (pure; no Streamlit)."""
    body_parts = [
        "Hallo Jochen,",
        "",
        "Feedback zum Earnie Online Szenario-Explorer:",
        "",
        (message or "").strip() or "(hier eintragen)",
        "",
    ]
    if attach_config:
        body_parts.extend(
            [
                "Ich stimme zu, dass die Konfigurations-ZIP für Tests und "
                "Bugfixes genutzt werden darf.",
                "",
                "Bitte die heruntergeladene Konfigurations-ZIP dieser E-Mail "
                "manuell anhängen (wird nicht automatisch angehängt).",
                "",
            ]
        )
    body_parts.append("— gesendet aus der Streamlit-Cloud")
    body = "\n".join(body_parts)
    return (
        f"mailto:{FEEDBACK_EMAIL}"
        f"?subject={quote(_FEEDBACK_SUBJECT, safe='')}"
        f"&body={quote(body, safe='')}"
    )


def _feedback_config_zip_filename() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"earnie_cloud_demo_config_{stamp}.zip"


def render_cloud_demo_feedback_banner() -> None:
    """Ask for feedback after SE simulation start; only in EARNIE_CLOUD_DEMO."""
    if not is_cloud_demo():
        return
    import logging

    import streamlit as st

    if not st.session_state.get(SESSION_SE_SIM_STARTED_KEY):
        return
    if st.session_state.get(SESSION_SE_FEEDBACK_DISMISSED_KEY):
        return

    st.info(
        "**Wie war die Simulation?**\n\n"
        "Sie haben gerade den **Szenario-Explorer** gestartet. "
        "Was hat gut funktioniert, was war unklar oder fehlte? "
        "Kurzes Feedback hilft uns, Earnie zu verbessern."
    )
    message = st.text_area(
        "Ihr Feedback (optional)",
        key="earnie_cloud_se_feedback_message",
        height=100,
        placeholder="z. B. Einrichtung, Ergebnisse, Verständnis der Charts …",
    )
    attach_config = st.checkbox(
        "Ich stimme zu, dass meine Konfiguration als ZIP der E-Mail "
        "angehängt und für Tests sowie Bugfixes verwendet werden darf.",
        key="earnie_cloud_se_feedback_attach_config",
    )
    if attach_config:
        try:
            from runtime_store.config_pack import build_config_pack_bytes

            pack = build_config_pack_bytes()
        except Exception as exc:  # noqa: BLE001 — surface to user
            logging.getLogger(__name__).exception(
                "cloud demo feedback config pack failed"
            )
            st.error(f"ZIP-Erstellung fehlgeschlagen: {exc}")
            pack = b""
        if pack:
            st.download_button(
                label="Konfigurations-ZIP herunterladen",
                data=pack,
                file_name=_feedback_config_zip_filename(),
                mime="application/zip",
                key="earnie_cloud_se_feedback_zip_download",
            )
            st.caption(
                "Die ZIP-Datei muss der E-Mail manuell als Anhang hinzugefügt werden."
            )

    mailto = build_cloud_demo_feedback_mailto(
        message,
        attach_config=attach_config,
    )
    col_mail, col_dismiss = st.columns(2)
    with col_mail:
        st.link_button(
            "Feedback per E-Mail vorbereiten",
            mailto,
            use_container_width=True,
        )
    with col_dismiss:
        if st.button(
            "Später",
            key="earnie_cloud_se_feedback_dismiss",
            use_container_width=True,
        ):
            st.session_state[SESSION_SE_FEEDBACK_DISMISSED_KEY] = True
            st.rerun()
