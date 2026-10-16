"""Unit tests for scripts.release_notes_collect."""
from __future__ import annotations

from datetime import date

import pytest

from scripts.release_notes_collect import (
    channel_of,
    classify_paths,
    classify_subject,
    group_commits,
    parse_erledigt,
    pick_baseline,
    published_release_tags,
    verifications_pending,
)


def test_pick_baseline_skips_prerelease_and_dev_tags():
    tags = ["2.7.0-dev.50", "v2.6.2-beta.1", "v2.6.2", "v2.6.1"]
    assert pick_baseline(tags, frozenset(tags)) == "v2.6.2"


def test_pick_baseline_skips_declined_candidate_without_published_release():
    tags = ["v2.6.1", "v2.6.0"]
    assert pick_baseline(tags, frozenset({"v2.6.0"})) == "v2.6.0"


def test_pick_baseline_fails_without_productive_tag():
    with pytest.raises(ValueError):
        pick_baseline(["v2.6.0-alpha.1", "2.7.0-dev.1"], frozenset())


def test_channel_of():
    assert channel_of("2.7.0") == "official"
    assert channel_of("2.7.0-alpha.3") == "pre-release"
    assert channel_of("2.7.0-rc.1") == "pre-release"


def test_channel_of_rejects_dev():
    with pytest.raises(ValueError, match="-dev"):
        channel_of("2.7.0-dev.59")


def test_channel_of_rejects_garbage():
    with pytest.raises(ValueError):
        channel_of("latest")


def test_classify_subject():
    assert classify_subject("fix(milp): x") == "fix"
    assert classify_subject("Merge branch 'a'") == "merge"
    assert classify_subject("no prefix here") == "other"


def test_group_commits_separates_noise():
    commits = [
        {"sha": "a", "subject": "backlog: sync", "issues": []},
        {"sha": "b", "subject": "ehal: new", "issues": []},
        {"sha": "c", "subject": "Merge x", "issues": []},
    ]
    groups, noise = group_commits(commits)
    assert list(groups) == ["ehal"]
    assert [c["sha"] for c in noise] == ["a", "c"]


def test_parse_erledigt_filters_by_date():
    text = (
        "# T\n\n### New (2026-10-16)\n\n- [x] a\n\n### Old (2026-09-01)\n\n- [x] b\n"
    )
    items = parse_erledigt(text, date(2026, 10, 5))
    assert [i["title"] for i in items] == ["New"]
    assert items[0]["body"] == "- [x] a"


def test_classify_paths():
    res = classify_paths(
        [
            "runtime_store/migration/registry.py",
            "docs/user-manual/x.md",
            "packaging/homeassistant-addon/earnie/config.yaml",
            "docker/compose/proxmox_productive.yml",
            "optimizer/core.py",
        ]
    )
    assert res["structural"] == ["runtime_store/migration/registry.py"]
    assert res["user_docs"] == ["docs/user-manual/x.md"]
    assert set(res["platforms"]) == {"Home Assistant", "Synology / Docker", "Proxmox"}


def test_verifications_pending_section():
    text = "## A\nx\n## Bugfix Verifications Pending\n- item\n## Z\ny\n"
    assert verifications_pending(text) == "- item"
    assert verifications_pending("## A\n") == ""


def test_published_release_tags_without_gh_fails_loud(monkeypatch):
    def _missing(*_a, **_k):
        raise FileNotFoundError("gh")

    monkeypatch.setattr("scripts.release_notes_collect.subprocess.run", _missing)
    with pytest.raises(ValueError, match="gh"):
        published_release_tags()


def test_published_release_tags_excludes_drafts(monkeypatch):
    class _R:
        returncode = 0
        stdout = '[{"tagName":"v1.0.0","isDraft":false},{"tagName":"v1.0.1","isDraft":true}]'
        stderr = ""

    monkeypatch.setattr("scripts.release_notes_collect.subprocess.run", lambda *a, **k: _R())
    assert published_release_tags() == frozenset({"v1.0.0"})


_CFG = {"dev_prefixes": ["shadow"], "dev_terms": ["Shadow Mode", "HouseSim"]}


def test_classify_entry_explicit_markers_win():
    from scripts.release_notes_collect import classify_entry

    assert classify_entry("**X** `[dev]`: a", "Topic", _CFG)["audience"] == "dev"
    assert classify_entry("**X** [feat] a", "Topic", _CFG)["audience"] == "feat"
    assert classify_entry("**Shadow Mode** `[qual]`", "Topic", _CFG)["audience"] == "qual"


def test_classify_entry_bugfix_counts_as_fix_but_dev_overrides():
    from scripts.release_notes_collect import classify_entry

    assert classify_entry("**Something broke**", "Bugfix - Foo", _CFG)["audience"] == "fix"
    assert classify_entry("**Bugfix x**", "Topic", _CFG)["audience"] == "fix"
    assert classify_entry("**Bugfix x** `[dev]`", "Topic", _CFG)["audience"] == "dev"


def test_classify_entry_unmarked_suggests_dev_from_terms_but_never_decides():
    from scripts.release_notes_collect import classify_entry

    res = classify_entry("**Recorder for Shadow Mode**", "Topic", _CFG)
    assert res == {"audience": "unmarked", "suggestion": "dev"}
    assert classify_entry("**Plain**", "Topic", _CFG) == {"audience": "unmarked", "suggestion": None}


def test_parse_erledigt_entries_use_top_level_checkboxes_only():
    text = "### T (2026-10-16)\n\n- [x] **A** `[feat]`\n  - [x] sub\n- [x] **B**\n"
    items = parse_erledigt(text, date(2026, 10, 1), _CFG)
    assert [(e["text"][:3], e["audience"]) for e in items[0]["entries"]] == [
        ("**A", "feat"),
        ("**B", "unmarked"),
    ]


def test_load_audience_config_real_file_is_valid():
    from scripts.release_notes_collect import load_audience_config

    cfg = load_audience_config()
    assert "shadow" in cfg["dev_prefixes"] and cfg["dev_terms"]


def test_load_audience_config_missing_fails_loud(tmp_path):
    from scripts.release_notes_collect import load_audience_config

    with pytest.raises(ValueError, match="missing"):
        load_audience_config(tmp_path / "nope.toml")
