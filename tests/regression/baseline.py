"""Golden baseline: which public commit a golden was recorded from, and drift since."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_UPDATE_GOLDEN = "update-golden"
SOURCE_GIT_LOG_BACKFILL = "git-log-backfill"
BASELINE_SOURCES = frozenset({SOURCE_UPDATE_GOLDEN, SOURCE_GIT_LOG_BACKFILL})

# Paths whose changes can move optimizer results (for the drift count).
CODE_PATHS = ("optimizer", "simulation", "runtime_store", "tests/fixtures", "config.py")
_CASES_PATHSPEC = ":(exclude)tests/regression/cases"


class DirtyWorktreeError(RuntimeError):
    """Uncommitted code changes would make the golden's baseline SHA unreproducible."""


def _git_raw(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(repo), stderr=subprocess.PIPE, text=True
    )


def _git(repo: Path, *args: str) -> str:
    return _git_raw(repo, *args).strip()


def dirty_paths(repo: Path) -> list[str]:
    """Uncommitted / untracked paths outside the case folders (gitignored excluded)."""
    # Unstripped: porcelain lines start with a status column that may be a space.
    out = _git_raw(repo, "status", "--porcelain=v1", "--", ".", _CASES_PATHSPEC)
    return [line[3:] for line in out.splitlines() if line.strip()]


def require_clean_worktree(repo: Path) -> None:
    dirty = dirty_paths(repo)
    if dirty:
        listing = "\n".join(f"  {p}" for p in dirty[:20])
        more = f"\n  … {len(dirty) - 20} more" if len(dirty) > 20 else ""
        raise DirtyWorktreeError(
            "--update-golden needs a clean public worktree (outside "
            "tests/regression/cases/) so the golden cites a reproducible commit. "
            f"Commit or stash first:\n{listing}{more}"
        )


def baseline_for_update(repo: Path) -> dict[str, Any]:
    return {
        "git_sha": _git(repo, "rev-parse", "HEAD"),
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE_UPDATE_GOLDEN,
    }


def backfill_baseline(repo: Path, expected_path: Path) -> dict[str, Any] | None:
    """Last commit that touched ``expected.json`` (None when never committed)."""
    rel = expected_path.resolve().relative_to(repo.resolve()).as_posix()
    out = _git(repo, "log", "-1", "--format=%H %cI", "--", rel)
    if not out:
        return None
    sha, committed_at = out.split(" ", 1)
    return {"git_sha": sha, "recorded_at": committed_at, "source": SOURCE_GIT_LOG_BACKFILL}


def baseline_drift(repo: Path, baseline_sha: str) -> dict[str, Any]:
    """Commit counts baseline..HEAD; ``error`` when the SHA is unknown or not an ancestor."""
    try:
        _git(repo, "merge-base", "--is-ancestor", baseline_sha, "HEAD")
    except subprocess.CalledProcessError:
        return {"error": f"{baseline_sha[:8]} is not an ancestor of HEAD (or unknown)"}
    span = f"{baseline_sha}..HEAD"
    return {
        "head_sha": _git(repo, "rev-parse", "HEAD"),
        "commits_total": int(_git(repo, "rev-list", "--count", span)),
        "commits_code": int(_git(repo, "rev-list", "--count", span, "--", *CODE_PATHS)),
    }


def bisect_commands(baseline_sha: str, case_id: str) -> list[str]:
    return [
        f"git bisect start HEAD {baseline_sha[:12]}",
        "git bisect run .venv/Scripts/python.exe -m scripts.run_regression "
        f"--case {case_id} --workers 1 "
        "--report backtesting_logs/regression/bisect_report.md",
    ]
