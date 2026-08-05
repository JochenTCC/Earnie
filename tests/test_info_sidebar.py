"""Tests for sidebar Info contact helpers."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

from ui.github_issue_url import build_github_issue_url
from ui.info_sidebar import (
    MANUAL_URL,
    SUPPORT_EMAIL,
    build_contact_bundle_bytes,
    build_mailto_url,
)
from ui.truth_banner import OFFICIAL_REPO_URL, SITE_URL


def test_manual_url_points_to_github_handbook():
    assert MANUAL_URL.startswith(OFFICIAL_REPO_URL)
    assert MANUAL_URL.endswith(
        "/blob/main/docs/user-manual/Benutzer-Handbuch-Earnie.md"
    )


def test_support_email_is_earnie_support():
    assert SUPPORT_EMAIL == "support@earnie-hems.com"
    assert SITE_URL == "https://earnie-hems.com"


def test_build_mailto_url_encodes_topic_and_description():
    url = build_mailto_url("Thema A", "Bitte prüfen.")
    assert url.startswith(f"mailto:{SUPPORT_EMAIL}?")
    assert "subject=" in url
    assert "body=" in url
    assert "Thema%20A" in url or "Thema+A" in url


def test_build_mailto_url_default_subject():
    url = build_mailto_url("", "")
    assert "Earnie%20Support" in url or "Earnie+Support" in url


def test_build_github_issue_url_used_for_kontakt():
    url = build_github_issue_url("Frage", "Hilfe", "Wie …?")
    assert "/issues/new" in url
    qs = parse_qs(urlparse(url).query)
    assert "question" in unquote(qs["labels"][0])


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
