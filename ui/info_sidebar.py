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
from ui.truth_banner import render_truth_banner

logger = logging.getLogger(__name__)

SUPPORT_EMAIL = "mail@techcreacon.com"
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
        st.link_button("E-Mail schreiben", mailto, use_container_width=True)
