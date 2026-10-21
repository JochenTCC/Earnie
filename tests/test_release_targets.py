"""scripts.release_targets — publish scope from the annotated release tag message."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import release_targets as rt

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-publish.yml"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Release v2.7.0\n\ntargets: both\n", "both"),
        ("Pre-release v2.7.0-alpha.3\n\ntargets: docker", "docker"),
        ("Release v2.7.0\n\n  Targets:  HA  \n", "ha"),
    ],
)
def test_parse_targets_reads_single_line(message, expected):
    assert rt.parse_targets(message) == expected


@pytest.mark.parametrize(
    ("message", "match"),
    [
        ("Release v2.7.0\n", "no 'targets"),
        ("targets: ha\ntargets: both\n", "several"),
        ("targets: loxone\n", "unknown"),
        ("targets:\n", "unknown"),
    ],
)
def test_parse_targets_rejects_missing_duplicate_or_unknown(message, match):
    with pytest.raises(rt.ReleaseTargetsError, match=match):
        rt.parse_targets(message)


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "c")
    monkeypatch.chdir(tmp_path)
    return git


def test_main_prints_targets_of_annotated_tag(git_repo, capsys):
    git_repo("-c", "user.name=t", "-c", "user.email=t@example.com",
             "tag", "-a", "v9.9.9", "-m", "Release v9.9.9", "-m", "targets: ha")
    assert rt.main(["--tag", "v9.9.9"]) == 0
    assert capsys.readouterr().out.strip() == "ha"


def test_main_fails_on_annotated_tag_without_targets(git_repo, capsys):
    git_repo("-c", "user.name=t", "-c", "user.email=t@example.com",
             "tag", "-a", "v9.9.9", "-m", "Release v9.9.9")
    assert rt.main(["--tag", "v9.9.9"]) == 1
    assert "::error::" in capsys.readouterr().err


def test_main_fails_on_lightweight_tag(git_repo, capsys):
    git_repo("tag", "v9.9.9")
    assert rt.main(["--tag", "v9.9.9"]) == 1
    assert "lightweight" in capsys.readouterr().err


def test_release_workflow_reads_targets_from_tag_on_push():
    """No silent 'both' on a tag push: the scope comes from the annotated tag message."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    gate = text.split("- name: Version gate", 1)[1].split("- name:", 1)[0]
    assert 'python -m scripts.release_targets --tag "${TAG}"' in gate
    assert 'git fetch --force --no-tags origin "refs/tags/${TAG}:refs/tags/${TAG}"' in gate
    assert 'TARGETS="both"' not in gate
    assert "GITHUB_STEP_SUMMARY" in gate
