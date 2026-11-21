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


def test_targets_skip_option_values() -> None:
    from scripts.run_pytest import _targets

    args = ["-q", "-k", "foo", "--maxfail", "5", "tests/test_a.py", "--tb=short", "-m", "slow"]
    assert _targets(args) == ["tests/test_a.py"]


def test_fast_lane_for_few_explicit_files(tmp_path) -> None:
    from scripts.run_pytest import _is_fast_lane, _should_queue

    (tmp_path / "tests").mkdir()
    for name in ("test_a.py", "test_b.py", "test_c.py", "test_d.py"):
        (tmp_path / "tests" / name).write_text("", encoding="utf-8")

    assert _is_fast_lane(["tests/test_a.py", "-q"], tmp_path)
    assert _is_fast_lane(["tests/test_a.py::test_x", "tests/test_b.py"], tmp_path)
    # Directory, no target, unknown path, too many files -> queue.
    assert not _is_fast_lane(["tests", "-q"], tmp_path)
    assert not _is_fast_lane(["-q"], tmp_path)
    assert not _is_fast_lane(["tests/missing.py"], tmp_path)
    assert not _is_fast_lane(
        [f"tests/test_{c}.py" for c in "abcd"], tmp_path
    )
    assert _should_queue(["tests", "-q"], None, tmp_path)
    assert not _should_queue(["tests/test_a.py"], None, tmp_path)
    assert not _should_queue(["--collect-only", "tests"], None, tmp_path)
    assert _should_queue(["tests/test_a.py"], True, tmp_path)
    assert not _should_queue(["tests"], False, tmp_path)


def test_split_queue_flags() -> None:
    from scripts.run_pytest import _split_queue_flags

    assert _split_queue_flags(["tests", "--queue"]) == (["tests"], True)
    assert _split_queue_flags(["--no-queue", "tests"]) == (["tests"], False)
    assert _split_queue_flags(["tests"]) == (["tests"], None)
