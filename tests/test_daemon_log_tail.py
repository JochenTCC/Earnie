"""Unit tests for Optimierer-Dienst earnie.log tail helper."""
from __future__ import annotations

from pathlib import Path

import pytest

from ui.pages.page_daemon import (
    filter_log_lines,
    parse_log_level,
    read_earnie_log_tail,
)


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


def test_parse_log_level_known_format() -> None:
    line = (
        "2026-08-05 13:42:43 [INFO] (optimizer.milp_consumers:620) - "
        "urgent-Regel [e_auto]: nur_urgent_fenster"
    )
    assert parse_log_level(line) == "INFO"
    assert parse_log_level("2026-08-05 [WARNING] boom") == "WARNING"
    assert parse_log_level("no level here") is None


def test_filter_log_lines_keeps_warning_when_info_deselected() -> None:
    text = "\n".join(
        [
            "2026-08-05 13:42:43 [INFO] (mod:1) - chatter",
            "2026-08-05 13:42:44 [WARNING] (mod:2) - attention",
            "Traceback (most recent call last):",
            '  File "main.py", line 1',
        ]
    )
    filtered = filter_log_lines(text, {"WARNING", "ERROR", "CRITICAL"})
    lines = filtered.splitlines()
    assert any("[WARNING]" in line for line in lines)
    assert not any("[INFO]" in line for line in lines)
    assert "Traceback (most recent call last):" in lines
    assert '  File "main.py", line 1' in lines


def test_filter_log_lines_empty_text() -> None:
    assert filter_log_lines("", {"INFO"}) == ""
