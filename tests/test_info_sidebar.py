"""Tests for sidebar Info contact helpers."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

from ui.info_sidebar import SUPPORT_EMAIL, build_contact_bundle_bytes, build_mailto_url


def test_build_mailto_url_encodes_topic_and_description():
    url = build_mailto_url("Thema A", "Bitte prüfen.")
    assert url.startswith(f"mailto:{SUPPORT_EMAIL}?")
    assert "subject=" in url
    assert "body=" in url
    assert "Thema%20A" in url or "Thema+A" in url


def test_build_mailto_url_default_subject():
    url = build_mailto_url("", "")
    assert "Earnie%20Support" in url or "Earnie+Support" in url


def test_build_contact_bundle_includes_pack_and_attachments():
    attachment = SimpleNamespace(
        name="notiz.txt",
        getvalue=lambda: b"hello",
    )
    payload = build_contact_bundle_bytes(
        [attachment],
        config_pack=b"PK\x03\x04fake",
    )
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
        assert "earnie_config_pack.zip" in names
        assert "anhänge/notiz.txt" in names
        assert archive.read("anhänge/notiz.txt") == b"hello"
