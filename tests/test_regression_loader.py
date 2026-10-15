"""Fast unit checks for the regression case loader (not marker=regression)."""
from __future__ import annotations

import pytest

from tests.regression.loader import DEFAULT_CASES_DIR, discover_case_dirs, load_case
from tests.regression.schema import validate_case_meta


def test_public_cases_discoverable():
    dirs = discover_case_dirs(DEFAULT_CASES_DIR)
    ids = {p.name for p in dirs}
    assert "REG-O-winter-jan" in ids
    assert "REG-S-negative-prices" in ids
    assert "REG-O-prod-eauto-deadline" in ids


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
