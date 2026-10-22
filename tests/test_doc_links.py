"""Tests for Streamlit → GitHub docs deep-link registry."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ui.doc_links import (
    BLOB_PREFIX,
    HANDBOOK_REL_PATH,
    MANUAL_URL,
    NAV_DOC_PAGE_KEYS,
    PAGE_DOCS,
    docs_blob_url,
    get_page_docs,
    markdown_doc_link,
)
from ui.truth_banner import OFFICIAL_REPO_URL


def test_docs_blob_url_without_fragment():
    url = docs_blob_url("docs/ui/charts.md")
    assert url == f"{BLOB_PREFIX}/docs/ui/charts.md"
    assert url.startswith(OFFICIAL_REPO_URL)


def test_docs_blob_url_with_fragment_normalizes_hash():
    url = docs_blob_url("docs/ui/betriebsmodi.md", "#szenario-explorer")
    assert url.endswith("/docs/ui/betriebsmodi.md#szenario-explorer")


def test_docs_blob_url_rejects_empty_path():
    with pytest.raises(ValueError, match="rel_path"):
        docs_blob_url("")


def test_manual_url_is_handbook_base():
    assert MANUAL_URL == docs_blob_url(HANDBOOK_REL_PATH)
    assert MANUAL_URL.endswith(
        "/blob/main/docs/user-manual/Benutzer-Handbuch-Earnie.md"
    )


def test_page_docs_registry_covers_nav_keys():
    assert set(PAGE_DOCS) == NAV_DOC_PAGE_KEYS


def test_every_page_docs_has_primary_url_and_label():
    for key, docs in PAGE_DOCS.items():
        assert docs.primary.label.strip(), key
        assert docs.primary.path.strip(), key
        assert docs.primary.url.startswith(BLOB_PREFIX), key
        if docs.primary.fragment:
            assert "#" not in docs.primary.fragment, key


def test_get_page_docs_unknown_returns_none():
    assert get_page_docs("not-a-page") is None
    assert get_page_docs("") is None


def test_markdown_doc_link_format():
    docs = get_page_docs("cockpit")
    assert docs is not None
    md = markdown_doc_link(docs.primary)
    assert md.startswith("[")
    assert "](https://github.com/JochenTCC/Earnie/blob/main/" in md
    assert "#monitor)" in md


def test_nav_url_paths_have_doc_entries(monkeypatch):
    """Known navigation url_path values must stay registered."""
    from ui import navigation

    monkeypatch.setattr(navigation, "is_setup_navigation_restricted", lambda: False)
    monkeypatch.setattr(navigation, "is_betrieb_unlocked", lambda: True)
    monkeypatch.setattr(navigation, "is_planning_ready", lambda: True)
    monkeypatch.setattr(navigation, "is_scenario_editor_unlocked", lambda: True)

    specs = navigation.build_page_specs(
        [
            "sunset2sunset",
            "scenario_explorer",
            "live_environment",
            "price_forecast",
        ]
    )
    paths = {spec.url_path for spec in specs if spec.url_path}
    missing = paths - NAV_DOC_PAGE_KEYS
    assert not missing, f"Nav pages without doc_links entry: {sorted(missing)}"


# --- Fragments must exist in the linked document ------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _github_slug(heading: str) -> str:
    """GitHub heading anchor: lowercase, drop punctuation, each space becomes a hyphen."""
    text = re.sub(r"[`*_]", "", heading).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def _anchors_of(markdown_path: Path) -> set[str]:
    anchors: set[str] = set()
    in_code = False
    for line in markdown_path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if heading:
            anchors.add(_github_slug(heading.group(1)))
        anchors.update(re.findall(r'<a\s+(?:id|name)="([^"]+)"', line))
    return anchors


def _all_doc_links():
    for key, docs in PAGE_DOCS.items():
        for link in (docs.primary, *docs.secondaries):
            if link.fragment:
                yield pytest.param(link, id=f"{key}:{link.label}")


@pytest.mark.parametrize("link", list(_all_doc_links()))
def test_doc_link_fragment_exists_in_target_document(link):
    anchors = _anchors_of(_REPO_ROOT / link.path)
    assert link.fragment in anchors, f"{link.path}#{link.fragment} not found"


def test_inbound_handbook_links_from_docs_resolve():
    anchors = _anchors_of(_REPO_ROOT / HANDBOOK_REL_PATH)
    broken: list[str] = []
    for md_path in (_REPO_ROOT / "docs").rglob("*.md"):
        if "dev" in md_path.relative_to(_REPO_ROOT / "docs").parts[:1]:
            continue
        for fragment in re.findall(
            r"user-manual/Benutzer-Handbuch-Earnie\.md#([^)\s]+)",
            md_path.read_text(encoding="utf-8"),
        ):
            if fragment not in anchors:
                broken.append(f"{md_path.relative_to(_REPO_ROOT)}#{fragment}")
    assert broken == []
