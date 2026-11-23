"""Golden writer: ``expected.json`` is written with LF on every OS (Bugfix 2026-11-23).

``write_text`` without ``newline`` translates ``\n`` to ``os.linesep``, so ``--update-golden``
and ``--backfill-baseline`` wrote CRLF on Windows (the repository keeps LF, ``.gitattributes``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import run_regression

_CASE_YAML = """id: REG-S-lf-check
title: LF check
level: L2
source: synthetic
anonymized: true
app_version: "2.8.0-dev"
window:
  start: "2026-01-14"
  end: "2026-01-14"
inputs:
  kind: backtesting_fixtures
"""


@pytest.fixture
def _no_env_side_effects(monkeypatch):
    for key in ("EARNIE_OFFLINE", "EARNIE_CBC_STRICT", "EARNIE_MILP_SOLVER"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    monkeypatch.setattr(run_regression, "_isolate_from_site_config", lambda: None)


def test_update_golden_writes_lf(tmp_path: Path, monkeypatch, _no_env_side_effects) -> None:
    from tests.regression import l2_runner

    case_dir = tmp_path / "REG-S-lf-check"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(_CASE_YAML, encoding="utf-8", newline="\n")
    monkeypatch.setattr(
        l2_runner,
        "run_l2",
        lambda case: {"status_optimal": 1, "cost_euro": 1.5, "plan_hash": None,
                      "plausibility_failures": 0.0, "inputs": {"files": {}}},
    )
    run_regression._run_one_case_payload(
        {"case_dir": str(case_dir), "update_golden": True, "baseline": None}
    )
    raw = (case_dir / "expected.json").read_bytes()
    assert b"\r\n" not in raw
    assert json.loads(raw)["metrics"]["cost_euro"] == 1.5


def test_backfill_baseline_writes_lf(tmp_path: Path, monkeypatch) -> None:
    from tests.regression import baseline as baseline_module
    from tests.regression.loader import RegressionCase

    case_dir = run_regression.ROOT / "backtesting_logs" / "lf_check_case"
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        monkeypatch.setattr(
            baseline_module,
            "backfill_baseline",
            lambda root, path: {"git_sha": "a" * 40, "recorded_at": "2026-11-23",
                                "source": "git-log-backfill"},
        )
        case = RegressionCase(case_dir=case_dir, meta={"id": "REG-S-lf"}, expected={"metrics": {}})
        assert run_regression._backfill_baselines([case]) == 0
        raw = (case_dir / "expected.json").read_bytes()
        assert b"\r\n" not in raw
        assert json.loads(raw)["baseline"]["git_sha"] == "a" * 40
    finally:
        (case_dir / "expected.json").unlink(missing_ok=True)
        case_dir.rmdir()
