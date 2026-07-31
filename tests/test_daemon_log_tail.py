"""Unit tests for Optimierer-Dienst earnie.log tail helper."""
from __future__ import annotations

from pathlib import Path

import pytest

from ui.pages.page_daemon import read_earnie_log_tail


def test_missing_log_returns_error(tmp_path: Path) -> None:
    text, err = read_earnie_log_tail(tmp_path / "missing.log")
    assert text is None
    assert err is not None
    assert "nicht gefunden" in err


def test_empty_log_returns_empty_string(tmp_path: Path) -> None:
    path = tmp_path / "earnie.log"
    path.write_text("", encoding="utf-8")
    text, err = read_earnie_log_tail(path)
    assert err is None
    assert text == ""


def test_tail_keeps_last_lines_only(tmp_path: Path) -> None:
    path = tmp_path / "earnie.log"
    lines = [f"line-{i}" for i in range(50)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    text, err = read_earnie_log_tail(path, max_lines=10)
    assert err is None
    assert text is not None
    assert text.splitlines() == lines[-10:]


def test_byte_window_drops_partial_first_line(tmp_path: Path) -> None:
    path = tmp_path / "earnie.log"
    # Seek into the middle of "AAAA\nBBBB\nCCCC" → drop partial A line.
    path.write_bytes(b"AAAA\nBBBB\nCCCC\n")
    text, err = read_earnie_log_tail(path, max_lines=10, max_bytes=10)
    assert err is None
    assert text is not None
    assert "AAAA" not in text
    assert "BBBB" in text or "CCCC" in text


def test_invalid_limits_raise() -> None:
    with pytest.raises(ValueError):
        read_earnie_log_tail(max_lines=0)
    with pytest.raises(ValueError):
        read_earnie_log_tail(max_bytes=0)
