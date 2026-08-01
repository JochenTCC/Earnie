"""Sidebar Info / About: Banner der Wahrheit, Version, Kontaktformular."""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime
from typing import Any
from urllib.parse import quote

import streamlit as st

from runtime_store.config_pack import build_config_pack_bytes
from ui.doc_links import MANUAL_URL
from ui.truth_banner import (
    SUPPORT_EMAIL,
    render_registry_status_caption,
    render_truth_banner,
)

logger = logging.getLogger(__name__)

_CONTACT_ZIP_PREFIX = "earnie_kontakt"


def build_mailto_url(topic: str, description: str) -> str:
    """Build a mailto URL with subject/body; reminder to attach the ZIP."""
    subject = (topic or "").strip() or "Earnie Support"
    body_parts = [
        (description or "").strip(),
        "",
        "Bitte die heruntergeladene Kontakt-ZIP (Konfiguration + Anhänge) "
        "dieser E-Mail manuell anhängen.",
    ]
    body = "\n".join(body_parts).strip()
    return (
        f"mailto:{SUPPORT_EMAIL}"
        f"?subject={quote(subject, safe='')}"
        f"&body={quote(body, safe='')}"
    )


def build_contact_bundle_bytes(
    attachments: list[Any] | None,
    *,
    config_pack: bytes | None = None,
) -> bytes:
    """ZIP with config pack plus optional uploaded attachments."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        pack = config_pack
        if pack is None:
            pack = build_config_pack_bytes()
        if pack:
            archive.writestr("earnie_config_pack.zip", pack)
        for uploaded in attachments or []:
            name = getattr(uploaded, "name", None) or "anhang.bin"
            data = uploaded.getvalue() if hasattr(uploaded, "getvalue") else bytes(uploaded)
            archive.writestr(f"anhänge/{name}", data)
    return buffer.getvalue()


def _contact_zip_filename() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{_CONTACT_ZIP_PREFIX}_{stamp}.zip"


def render_info_sidebar() -> None:
    """Info / About expander: attribution banner, version, contact form."""
    with st.sidebar.expander("Info / About", expanded=False):
        render_truth_banner(where="inline")
        render_registry_status_caption()
        st.link_button(
            "Benutzer-Handbuch",
            MANUAL_URL,
            width="stretch",
        )
        st.markdown("#### Kontakt")
        st.caption(
            f"Anfragen an {SUPPORT_EMAIL}. Zuerst ZIP sammeln, dann E-Mail "
            "schreiben und die ZIP-Datei manuell als Anhang hinzufügen "
            "(wird nicht automatisch angehängt)."
        )
        topic = st.text_input("Thema", key="info_contact_topic")
        description = st.text_area("Beschreibung", key="info_contact_description")
        attachments = st.file_uploader(
            "Anhänge",
            accept_multiple_files=True,
            key="info_contact_attachments",
        )
        try:
            bundle = build_contact_bundle_bytes(list(attachments or []))
        except Exception as exc:  # noqa: BLE001 — surface to user
            st.error(f"ZIP-Erstellung fehlgeschlagen: {exc}")
            logger.exception("contact bundle export failed")
            bundle = b""
        if bundle:
            st.download_button(
                label="Informationen in ZIP sammeln",
                data=bundle,
                file_name=_contact_zip_filename(),
                mime="application/zip",
                key="info_contact_zip_download",
            )
            st.caption(
                "Die ZIP-Datei muss der E-Mail manuell als Anhang hinzugefügt werden."
            )
        mailto = build_mailto_url(topic, description)
        st.link_button("E-Mail schreiben", mailto, width="stretch")


def render_missing_next_month_tariff_sidebar() -> None:
    """Warn near month-end when live monthly_table tariffs lack next month."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import config
    from data.tariff_pricing import (
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
