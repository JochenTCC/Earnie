"""Tests for GitHub Issues URL builder (Kontakt intake)."""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from ui.github_issue_url import ISSUE_KIND_LABELS, build_github_issue_url
from ui.truth_banner import OFFICIAL_REPO_URL


def test_issue_kind_labels_cover_four_types():
    assert set(ISSUE_KIND_LABELS) == {
        "Bug",
        "Änderungswunsch",
        "Verbesserung",
        "Frage",
    }


def test_build_github_issue_url_encodes_title_body_labels():
    url = build_github_issue_url(
        "Bug",
        "Thema A",
        "Bitte prüfen.",
        version="2.4.0-test",
    )
    assert url.startswith(f"{OFFICIAL_REPO_URL}/issues/new?")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    title = unquote(qs["title"][0])
    body = unquote(qs["body"][0])
    labels = unquote(qs["labels"][0])
    assert title.startswith("[Bug]")
    assert "Thema A" in title
    assert "Bitte prüfen." in body
    assert "2.4.0-test" in body
    assert "öffentlich" in body
    assert "needs-triage" in labels
    assert "bug" in labels.split(",")


def test_build_github_issue_url_extra_labels_and_default_topic():
    url = build_github_issue_url(
        "Verbesserung",
        "",
        "",
        extra_labels=("cloud-demo",),
    )
    qs = parse_qs(urlparse(url).query)
    title = unquote(qs["title"][0])
    labels = unquote(qs["labels"][0]).split(",")
    assert "[Improvement]" in title
    assert "Earnie Feedback" in title
    assert "cloud-demo" in labels
    assert "improvement" in labels
