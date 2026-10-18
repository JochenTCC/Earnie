"""run_regression --compare-at: slot diff, summary, worktree guards."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from tests.regression.compare_at import (
    CompareAtError,
    build_slot_diff,
    default_worktree_root,
    resolve_commit,
    temp_worktree,
    write_comparison,
)


def _slots(index: list[str], pv: list[float], export: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"pv_kw": pv, "export_kwh": export},
        index=pd.DatetimeIndex(pd.to_datetime(index), name="ts"),
    )


def _trace(metrics: dict, inputs_series: str = "s", **extra) -> dict:
    return {
        "level": "L2",
        "metrics": metrics,
        "plan_hash": None,
        "inputs": {"files": {"f": "1"}, "series": {"pv_kw": inputs_series}, "sums": {}},
        "pv_shape_error": None,
        "slots": True,
        **extra,
    }


def test_build_slot_diff_outer_joins_and_computes_delta():
    base = _slots(["2026-06-25 10:00", "2026-06-25 10:15"], [1.0, 2.0], [0.1, 0.2])
    head = _slots(["2026-06-25 10:15", "2026-06-25 10:30"], [3.0, 4.0], [0.2, 0.3])
    diff = build_slot_diff(base, head)
    assert list(diff.columns) == [
        "pv_kw_base", "pv_kw_head", "pv_kw_delta",
        "export_kwh_base", "export_kwh_head", "export_kwh_delta",
    ]
    assert len(diff) == 3
    assert diff.loc["2026-06-25 10:15", "pv_kw_delta"] == pytest.approx(1.0)
    assert pd.isna(diff.loc["2026-06-25 10:00", "pv_kw_head"])


def test_write_comparison_summary(tmp_path: Path):
    base_dir, head_dir, out_dir = tmp_path / "b", tmp_path / "h", tmp_path / "out"
    for d in (base_dir, head_dir, out_dir):
        d.mkdir()
    idx = ["2026-06-25 02:00", "2026-06-25 12:00"]
    _slots(idx, [0.0, 5.0], [0.0, 1.0]).to_csv(base_dir / "slots.csv", index_label="ts")
    _slots(idx, [3.0, 3.0], [0.7, 0.7]).to_csv(head_dir / "slots.csv", index_label="ts")

    summary = write_comparison(
        case_id="REG-X",
        base_sha="a" * 40,
        head_label="`bbbbbbbb`",
        base_trace=_trace({"cost_euro": -1.0, "n_slots": 2}),
        head_trace=_trace(
            {"cost_euro": -1.5, "n_slots": 2},
            inputs_series="t",
            pv_shape_error="REG-X: PV > 0 at night",
        ),
        base_dir=base_dir,
        head_dir=head_dir,
        out_dir=out_dir,
    )
    text = summary.read_text(encoding="utf-8")
    assert "# Compare `REG-X`: `aaaaaaaa` → `bbbbbbbb`" in text
    assert "**PV shape guard (head)**: REG-X: PV > 0 at night" in text
    assert "| `cost_euro` **≠** | -1.0000 | -1.5000 | -0.5000 | -50.00% |" in text
    assert "| `n_slots` | 2 | 2 |" in text
    assert "- effective series changed: pv_kw" in text
    assert "| `pv_kw` **≠** | 2/2 | 3.0000 | 2026-06-25 02:00:00 |" in text
    for name in ("base_slots.csv", "head_slots.csv", "diff.csv"):
        assert (out_dir / name).is_file()


def test_write_comparison_without_slots(tmp_path: Path):
    trace = {**_trace({"cost_euro": 1.0}), "level": "L1", "slots": False, "plan_hash": "h"}
    summary = write_comparison(
        case_id="REG-L1", base_sha="a" * 40, head_label="`b`",
        base_trace=trace, head_trace=trace,
        base_dir=tmp_path, head_dir=tmp_path, out_dir=tmp_path,
    )
    text = summary.read_text(encoding="utf-8")
    assert "No per-slot trace for this level" in text
    assert "- files changed: none" in text


def test_default_worktree_root_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EARNIE_COMPARE_WORKTREE_ROOT", str(tmp_path / "w"))
    assert default_worktree_root(tmp_path) == tmp_path / "w"
    monkeypatch.delenv("EARNIE_COMPARE_WORKTREE_ROOT")
    repo = tmp_path / "Earnie"
    assert default_worktree_root(repo) == tmp_path.resolve() / "earnie-compare-wt"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "a.txt").write_text("1", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "c1")
    return path


def test_git_calls_ignore_hook_exported_git_dir(repo: Path, tmp_path: Path, monkeypatch):
    """Inside a git hook GIT_DIR / GIT_INDEX_FILE point at the hook's repo; cwd must win."""
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    expected = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    ).strip()
    assert resolve_commit(repo, "HEAD") == expected


def test_resolve_commit_rejects_unknown_ref(repo: Path):
    assert resolve_commit(repo, "HEAD") == _git(repo, "rev-parse", "HEAD")
    with pytest.raises(CompareAtError, match="rev-parse"):
        resolve_commit(repo, "no-such-ref")


def test_temp_worktree_created_and_removed(repo: Path, tmp_path: Path):
    sha = _git(repo, "rev-parse", "HEAD")
    root = tmp_path / "wt"
    with temp_worktree(repo, sha, root, keep=False) as tree:
        assert (tree / "a.txt").read_text(encoding="utf-8") == "1"
    assert not (root / sha[:10]).exists()
    assert str(root) not in _git(repo, "worktree", "list")


def test_temp_worktree_refuses_existing_path(repo: Path, tmp_path: Path):
    sha = _git(repo, "rev-parse", "HEAD")
    (tmp_path / "wt" / sha[:10]).mkdir(parents=True)
    with pytest.raises(CompareAtError, match="already exists"):
        with temp_worktree(repo, sha, tmp_path / "wt", keep=False):
            pass
