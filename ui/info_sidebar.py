"""Sidebar Info / About: Banner der Wahrheit, Version, Kontaktformular."""
from __future__ import annotations

import logging
from urllib.parse import quote

import streamlit as st

from ui.doc_links import MANUAL_URL
from ui.github_issue_url import ISSUE_KIND_LABELS, build_github_issue_url
from ui.truth_banner import (
    OFFICIAL_REPO_URL,
    SITE_URL,
    SUPPORT_EMAIL,
    render_registry_status_caption,
    render_truth_banner,
)
from version import __version__

logger = logging.getLogger(__name__)

def build_mailto_url(topic: str, description: str) -> str:
    """Build a private-support mailto (Layer C); reminder to attach the support package."""
    subject = (topic or "").strip() or "Earnie Support"
    body_parts = [
        (description or "").strip(),
        "",
        "Bitte das Support-Paket (Seitenleiste → Sichern & Übertragen) "
        "dieser E-Mail manuell anhängen.",
    ]
    body = "\n".join(body_parts).strip()
    return (
        f"mailto:{SUPPORT_EMAIL}"
        f"?subject={quote(subject, safe='')}"
        f"&body={quote(body, safe='')}"
    )


def _render_info_links() -> None:
    st.link_button(
        "Benutzer-Handbuch",
        MANUAL_URL,
        width="stretch",
    )
    st.link_button("Website", SITE_URL, width="stretch")
    st.link_button(
        "GitHub / Issues",
        f"{OFFICIAL_REPO_URL.rstrip('/')}/issues",
        width="stretch",
    )


def _render_contact_inputs() -> tuple[str, str, str]:
    """Art / Thema / Beschreibung; returns them in that order."""
    st.markdown("#### Kontakt")
    st.caption(
        "Standardweg: **öffentliches** GitHub-Issue. Keine Passwörter, "
        "Hostnamen, Kundennamen oder vollständigen Config-/Debug-Dumps "
        "einfügen. Ein Support-Paket (Konfiguration, Logs, Anhänge) gibt es "
        "unter **Sichern & Übertragen** — es bleibt lokal; nur sichere "
        "Ausschnitte pasten."
    )
    kind = st.selectbox(
        "Art",
        options=list(ISSUE_KIND_LABELS),
        key="info_contact_kind",
    )
    topic = st.text_input("Thema", key="info_contact_topic")
    description = st.text_area("Beschreibung", key="info_contact_description")
    return kind, topic, description


def _render_private_support_expander(topic: str, description: str) -> None:
    with st.expander("Privater Support (Registry / vertraulich)"):
        st.caption(
            "Nur wenn öffentliche Issues ungeeignet sind: Registry-"
            "Fingerprint, Zugangsdaten, Support-Paket. "
            f"Adresse: {SUPPORT_EMAIL}."
        )
        private_mailto = build_mailto_url(topic, description)
        st.link_button(
            "Private E-Mail vorbereiten",
            private_mailto,
            width="stretch",
        )


def render_info_sidebar() -> None:
    """Info / About expander: attribution banner, version, contact form."""
    with st.sidebar.expander("Info / About", expanded=False):
        render_truth_banner(where="inline")
        render_registry_status_caption()
        _render_info_links()
        kind, topic, description = _render_contact_inputs()
        issue_url = build_github_issue_url(
            kind,
            topic,
            description,
            version=__version__,
        )
        st.link_button("GitHub-Issue öffnen", issue_url, width="stretch")
        _render_private_support_expander(topic, description)


def render_missing_next_month_tariff_sidebar() -> None:
    """Warn near month-end when live monthly_table tariffs lack next month."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import config
    from house_config.tariff_month_hints import (
        is_within_days_of_next_month,
        missing_next_month_tariff_hints,
        next_calendar_month,
    )

    try:
        if config.is_runtime_params_deferred():
            return
        resolved = config.get_resolved_runtime_settings()
    except Exception:  # noqa: BLE001 — sidebar must not break the app
        return
    if not isinstance(resolved, dict):
        return

    try:
        tz_name = config.CONFIG.get_planning_timezone()
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        now = datetime.now().astimezone()
    if not is_within_days_of_next_month(now, days=2):
        return
    year, month = next_calendar_month(now.year, now.month)
    hints = missing_next_month_tariff_hints(
        import_tariff=resolved.get("_import_tariff_spec"),
        export_tariff=resolved.get("_export_tariff_spec"),
        year=year,
        month=month,
    )
    if not hints:
        return
    lines = "\n".join(f"- {h}" for h in hints)
    st.sidebar.warning(
        f"**Monatstarif fehlt für {year}-{month:02d}** (nächster Monat):\n\n"
        f"{lines}\n\n"
        "Temporär Vorjahres-/Vormonatswert. "
        "Bitte im **Szenarienkonfigurator** den Cent/kWh-Wert ergänzen."
    )
