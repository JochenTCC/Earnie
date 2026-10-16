"""Unit tests for scripts.release_notes_finalize."""
from __future__ import annotations

import pytest

from scripts.release_notes_finalize import (
    check_final,
    finalize,
    finalize_text,
    reset_unreleased,
)

DRAFT = (
    "<!-- status: DRAFT — not reviewed. Generated from v2.6.2..abc -->\n"
    "## Earnie 2.7.0\n\nEin Satz. <!-- src: abc123 -->\n\n\n\n### Highlights\n\n- x\n"
)


def test_requires_approval_for_draft_status():
    with pytest.raises(ValueError, match="approved"):
        finalize_text(DRAFT, approved=False)


def test_strips_status_and_src_comments():
    out = finalize_text(DRAFT, approved=True)
    assert out.startswith("## Earnie 2.7.0")
    assert "<!--" not in out
    assert "\n\n\n" not in out


def test_unresolved_review_marker_blocks_even_when_approved():
    with pytest.raises(ValueError, match="REVIEW"):
        finalize_text(DRAFT + "<!-- REVIEW: unsure -->\n", approved=True)


def test_reset_unreleased_keeps_header_only():
    text = "# Unreleased\n\nHinweis.\n\n## Breaking\n\n- a\n"
    assert reset_unreleased(text) == "# Unreleased\n\nHinweis.\n"


def _setup(tmp_path, version="2.7.0"):
    notes = tmp_path / ".github" / "release-notes"
    (notes / "drafts").mkdir(parents=True)
    (notes / "drafts" / f"v{version}.draft.md").write_text(DRAFT, encoding="utf-8")
    (notes / "UNRELEASED.md").write_text("# U\n\n## Breaking\n\n- a\n", encoding="utf-8")
    return notes


def test_finalize_official_resets_unreleased(tmp_path):
    notes = _setup(tmp_path)
    path = finalize("2.7.0", approved=True, repo=tmp_path)
    assert path == notes / "v2.7.0.md"
    assert not (notes / "drafts" / "v2.7.0.draft.md").exists()
    assert (notes / "UNRELEASED.md").read_text(encoding="utf-8") == "# U\n"


def test_finalize_prerelease_keeps_unreleased(tmp_path):
    notes = _setup(tmp_path, "2.7.0-alpha.1")
    finalize("2.7.0-alpha.1", approved=True, repo=tmp_path)
    assert "- a" in (notes / "UNRELEASED.md").read_text(encoding="utf-8")


def test_finalize_rejects_dev_missing_draft_and_existing_final(tmp_path):
    with pytest.raises(ValueError, match="-dev"):
        finalize("2.7.0-dev.5", approved=True, repo=tmp_path)
    with pytest.raises(ValueError, match="not found"):
        finalize("2.7.0", approved=True, repo=tmp_path)
    notes = _setup(tmp_path)
    (notes / "v2.7.0.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        finalize("2.7.0", approved=True, repo=tmp_path)


def test_check_final(tmp_path):
    notes = tmp_path / ".github" / "release-notes"
    notes.mkdir(parents=True)
    with pytest.raises(ValueError, match="missing"):
        check_final("2.7.0", repo=tmp_path)
    (notes / "v2.7.0.md").write_text(DRAFT, encoding="utf-8")
    with pytest.raises(ValueError, match="unreviewed"):
        check_final("2.7.0", repo=tmp_path)
    (notes / "v2.7.0.md").write_text("## Earnie 2.7.0\n\nok\n", encoding="utf-8")
    assert check_final("2.7.0", repo=tmp_path) == notes / "v2.7.0.md"
    with pytest.raises(ValueError, match="-dev"):
        check_final("2.7.0-dev.1", repo=tmp_path)
