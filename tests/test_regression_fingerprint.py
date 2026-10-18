"""Regression input fingerprint, golden baseline and inputs verdict."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from tests.regression.baseline import (
    SOURCE_GIT_LOG_BACKFILL,
    DirtyWorktreeError,
    backfill_baseline,
    baseline_drift,
    dirty_paths,
    require_clean_worktree,
)
from tests.regression.compare import CompareResult, compare_case
from tests.regression.fingerprint import (
    diff_inputs,
    file_digest,
    l2_input_fingerprint,
    series_digest,
)
from tests.regression.report import write_markdown_report
from tests.regression.schema import validate_expected

_EXPECTED = {
    "engine": {"earnie_version": "1.0", "solver": "highs", "solver_mode": "strict"},
    "tolerances": {"default_pct": 0.05, "per_metric_pct": {}},
    "invariants": [],
    "metrics": {"cost_euro": 1.0},
}


def _inputs(pv: str = "a", fixture: str = "f1", pv_kwh: float = 10.0) -> dict:
    return {
        "files": {"fixtures/config.json": fixture},
        "series": {"pv_kw": pv, "k_act": "k"},
        "sums": {"pv_kwh": pv_kwh},
    }


def _tier(result: CompareResult, name: str):
    return next(t for t in result.tiers if t.name == name)


def test_json_digest_ignores_key_order_and_whitespace(tmp_path: Path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text('{"x": 1, "y": [1, 2]}', encoding="utf-8")
    b.write_text('{\n  "y": [1,2],\n  "x": 1\n}\n', encoding="utf-8")
    assert file_digest(a) == file_digest(b)


def test_csv_digest_ignores_line_endings(tmp_path: Path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_bytes(b"ts,v\n1,2\n")
    b.write_bytes(b"ts,v\r\n1,2\r\n")
    assert file_digest(a) == file_digest(b)


def test_series_digest_rounds_noise_and_maps_nan():
    assert series_digest([1.0, 2.0]) == series_digest([1.0 + 1e-9, 2.0])
    assert series_digest([1.0, 2.0]) != series_digest([1.0, 2.001])
    assert series_digest([float("nan")]) == series_digest([None])


def test_l2_fingerprint_requires_input_columns(tmp_path: Path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    df = pd.DataFrame({"pv_kw": [1.0], "baseload_kw": [0.5], "k_act": [10.0]})
    with pytest.raises(KeyError, match="k_push_act"):
        l2_input_fingerprint(fixtures_root=tmp_path, case_inputs={}, result_df=df)


def test_l2_fingerprint_sums_and_skips_readme(tmp_path: Path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "README.md").write_text("doc", encoding="utf-8")
    df = pd.DataFrame(
        {
            "pv_kw": [4.0, 4.0],
            "baseload_kw": [1.0, 1.0],
            "k_act": [10.0, 20.0],
            "k_push_act": [float("nan"), 8.0],
        }
    )
    fp = l2_input_fingerprint(fixtures_root=tmp_path, case_inputs={"a": 1}, result_df=df)
    assert set(fp["files"]) == {"fixtures/config.json", "case.inputs"}
    assert fp["sums"] == {
        "n_slots": 2.0,
        "pv_kwh": 2.0,
        "baseload_kwh": 0.5,
        "k_act_mean": 15.0,
    }


def test_l2_fingerprint_includes_climate_fixture_subdir(tmp_path: Path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    climate = tmp_path / "open_meteo" / "47.4_9.7_2025.json"
    climate.parent.mkdir()
    climate.write_text('{"data": [[18.0, 0.0]]}', encoding="utf-8")
    df = pd.DataFrame({col: [1.0] for col in ("pv_kw", "baseload_kw", "k_act", "k_push_act")})

    before = l2_input_fingerprint(fixtures_root=tmp_path, case_inputs={}, result_df=df)
    assert "fixtures/open_meteo/47.4_9.7_2025.json" in before["files"]

    climate.write_text('{"data": [[-2.0, 0.0]]}', encoding="utf-8")
    after = l2_input_fingerprint(fixtures_root=tmp_path, case_inputs={}, result_df=df)
    assert diff_inputs(before, after)["files"] == ["fixtures/open_meteo/47.4_9.7_2025.json"]


def test_diff_inputs_reports_changed_keys_and_sums():
    diff = diff_inputs(_inputs(), _inputs(pv="b", pv_kwh=12.0))
    assert diff == {"files": [], "series": ["pv_kw"], "sums": {"pv_kwh": (10.0, 12.0)}}


@pytest.mark.parametrize(
    ("actual", "verdict_part"),
    [
        (_inputs(pv="b"), "effective inputs changed"),
        (_inputs(fixture="f2"), "input files changed but effective inputs identical"),
        (_inputs(), "inputs identical"),
    ],
)
def test_inputs_verdict_on_metric_failure(actual: dict, verdict_part: str):
    result = compare_case(
        case_id="C",
        expected={**_EXPECTED, "inputs": _inputs()},
        actual_metrics={"cost_euro": 2.0},
        invariant_failures=[],
        actual_inputs=actual,
    )
    assert not result.passed
    verdicts = [m for m in _tier(result, "inputs").messages if m.startswith("verdict:")]
    assert len(verdicts) == 1 and verdict_part in verdicts[0]


def test_inputs_tier_is_informational_and_silent_verdict_when_metrics_pass():
    result = compare_case(
        case_id="C",
        expected={**_EXPECTED, "inputs": _inputs()},
        actual_metrics={"cost_euro": 1.0},
        invariant_failures=[],
        actual_inputs=_inputs(pv="b"),
        actual_engine={"earnie_version": "2.0"},
    )
    assert result.passed
    messages = _tier(result, "inputs").messages
    assert "engine: earnie_version 1.0 → 2.0" in messages
    assert not any(m.startswith("verdict:") for m in messages)


def test_missing_expected_fingerprint_shows_actual_sums():
    result = compare_case(
        case_id="C",
        expected=_EXPECTED,
        actual_metrics={"cost_euro": 2.0},
        invariant_failures=[],
        actual_inputs=_inputs(),
    )
    messages = _tier(result, "inputs").messages
    assert "actual: pv_kwh=10.0" in messages
    assert any("cannot separate input drift" in m for m in messages)


def test_plan_diff_marked_na_without_hashes():
    result = compare_case(
        case_id="C", expected=_EXPECTED, actual_metrics={"cost_euro": 1.0},
        invariant_failures=[],
    )
    assert _tier(result, "plan_diff").messages == ["n/a (no plan hash for this case level)"]


def test_schema_rejects_short_baseline_sha():
    bad = {**_EXPECTED, "baseline": {"git_sha": "abc", "recorded_at": "x",
                                     "source": SOURCE_GIT_LOG_BACKFILL}}
    with pytest.raises(ValueError, match="40-char"):
        validate_expected(bad, case_id="C")


def test_schema_rejects_inputs_without_layers():
    with pytest.raises(ValueError, match="inputs.series"):
        validate_expected({**_EXPECTED, "inputs": {"files": {}}}, case_id="C")


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    case_dir = tmp_path / "tests" / "regression" / "cases" / "C"
    case_dir.mkdir(parents=True)
    (case_dir / "expected.json").write_text("{}", encoding="utf-8")
    (tmp_path / "optimizer").mkdir()
    (tmp_path / "optimizer" / "m.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def test_dirty_check_ignores_case_folders(repo: Path):
    (repo / "tests" / "regression" / "cases" / "C" / "expected.json").write_text(
        '{"x": 1}', encoding="utf-8"
    )
    assert dirty_paths(repo) == []
    require_clean_worktree(repo)


def test_dirty_check_fails_on_code_change(repo: Path):
    (repo / "optimizer" / "m.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(DirtyWorktreeError, match="optimizer/m.py"):
        require_clean_worktree(repo)


def test_backfill_and_drift(repo: Path):
    base_sha = _git(repo, "rev-parse", "HEAD")
    baseline = backfill_baseline(
        repo, repo / "tests" / "regression" / "cases" / "C" / "expected.json"
    )
    assert baseline is not None
    assert baseline["git_sha"] == base_sha
    assert baseline["source"] == SOURCE_GIT_LOG_BACKFILL

    (repo / "optimizer" / "m.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "notes.txt").write_text("n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "code")
    (repo / "notes.txt").write_text("n2", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "notes")

    drift = baseline_drift(repo, base_sha)
    assert drift["commits_total"] == 2
    assert drift["commits_code"] == 1
    assert "error" in baseline_drift(repo, "0" * 40)


def test_report_shows_baseline_and_bisect_for_failing_case(tmp_path: Path):
    sha = "a" * 40
    result = compare_case(
        case_id="C", expected=_EXPECTED, actual_metrics={"cost_euro": 2.0},
        invariant_failures=[],
    )
    result.baseline = {
        "git_sha": sha,
        "recorded_at": "2026-10-15",
        "source": SOURCE_GIT_LOG_BACKFILL,
        "drift": {"head_sha": "b" * 40, "commits_total": 3, "commits_code": 1},
    }
    path = write_markdown_report(tmp_path / "r.md", results=[result], public_sha="x")
    text = path.read_text(encoding="utf-8")
    assert "3 commits, 1 in code paths" in text
    assert f"git bisect start HEAD {sha[:12]}" in text
    assert "- **inputs**: info" in text
