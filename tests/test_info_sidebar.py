"""Tests for sidebar Info contact helpers."""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from ui.github_issue_url import build_github_issue_url
from ui.info_sidebar import (
    MANUAL_URL,
    SUPPORT_EMAIL,
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
