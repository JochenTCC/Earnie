"""Unit tests for scripts.run_pytest parallel defaults."""
from __future__ import annotations

import importlib.util

import pytest

from scripts.run_pytest import _has_numprocesses_flag, _should_default_parallel

_HAS_XDIST = importlib.util.find_spec("xdist") is not None


def test_has_numprocesses_flag_variants() -> None:
    assert _has_numprocesses_flag(["-n", "auto"])
    assert _has_numprocesses_flag(["-n4"])
    assert _has_numprocesses_flag(["--numprocesses", "2"])
    assert _has_numprocesses_flag(["--numprocesses=0"])
    assert not _has_numprocesses_flag(["tests", "-q"])


def test_should_default_parallel_respects_sequential_flags() -> None:
    assert not _should_default_parallel(["--dead-fixtures"])
    assert not _should_default_parallel(["--collect-only", "tests"])
    assert not _should_default_parallel(["-n", "0", "tests"])


@pytest.mark.skipif(not _HAS_XDIST, reason="pytest-xdist not installed")
def test_should_default_parallel_when_xdist_present() -> None:
    assert _should_default_parallel(["tests", "-q"])
