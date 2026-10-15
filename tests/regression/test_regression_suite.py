"""Pytest entry for the release regression suite (deselected by default)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from scripts.run_regression import main as run_regression_main
from tests.regression.loader import DEFAULT_CASES_DIR, discover_case_dirs


@pytest.mark.regression
def test_release_regression_suite_public_cases():
    cases = discover_case_dirs(DEFAULT_CASES_DIR)
    assert cases, "expected public cases under tests/regression/cases/"
    workers = min(os.cpu_count() or 1, len(cases))
    rc = run_regression_main(["--workers", str(workers)])
    assert rc == 0
