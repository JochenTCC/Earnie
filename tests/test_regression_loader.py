"""Fast unit checks for the regression case loader (not marker=regression)."""
from __future__ import annotations

import pytest

from tests.regression.loader import (
    DEFAULT_CASES_DIR,
    ENV_PRIVATE_CASES_DIR,
    SKIP_PRIVATE_ROOT_MISSING,
    discover_case_dirs,
    load_case,
    resolve_private_cases_dir,
)
from tests.regression.schema import validate_case_meta
from scripts import run_regression


def test_public_cases_discoverable():
    dirs = discover_case_dirs(DEFAULT_CASES_DIR)
    ids = {p.name for p in dirs}
    assert "REG-O-winter-jan" in ids
    assert "REG-S-negative-prices" in ids
    assert "REG-O-prod-eauto-deadline" in ids


def test_case_roots_skip_when_private_missing(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_PRIVATE_CASES_DIR, str(tmp_path / "missing-cases"))
    assert resolve_private_cases_dir() is None
    args = run_regression._parse_args([])
    roots, skipped, private = run_regression._case_roots(args)
    assert DEFAULT_CASES_DIR in roots
    assert private is None
    assert SKIP_PRIVATE_ROOT_MISSING in skipped


def test_load_l1_case_meta():
    case = load_case(DEFAULT_CASES_DIR / "REG-O-winter-jan", require_expected=True)
    assert case.level == "L1"
    assert case.expected is not None
    assert case.expected["tolerances"]["default_pct"] == 0.05


def test_case_id_must_match_folder():
    with pytest.raises(ValueError, match="must match folder name"):
        validate_case_meta(
            {
                "id": "REG-WRONG",
                "title": "x",
                "level": "L1-invariants",
                "source": "own",
                "anonymized": True,
                "prod_dump_id": "eauto_deadline_missed_2026-06-27",
            },
            case_dir_name="REG-O-prod-eauto-deadline",
        )
