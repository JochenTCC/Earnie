"""Unit tests for SizeAndTimeRotatingFileHandler / setup_logging rotation."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

import logger_config


@pytest.fixture(autouse=True)
def _clear_root_handlers():
    root = logging.getLogger()
    root.handlers.clear()
    yield
    for handler in list(root.handlers):
        handler.close()
    root.handlers.clear()


def _archive_siblings(log_path: Path) -> list[Path]:
    prefix = log_path.name + "."
    return sorted(
        p for p in log_path.parent.iterdir() if p.name.startswith(prefix) and p.is_file()
    )


def test_size_rollover_creates_archive_and_caps_active_file(tmp_path: Path) -> None:
    log_path = tmp_path / "earnie.log"
    handler = logger_config.SizeAndTimeRotatingFileHandler(
        str(log_path),
        when="W0",
        maxBytes=200,
        backupCount=8,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("test_size_rollover")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.propagate = False

    for i in range(40):
        log.info("payload-%s-%s", i, "x" * 40)
    handler.flush()

    archives = _archive_siblings(log_path)
    assert archives, "expected at least one size-rotated archive"
    assert log_path.is_file()
    assert log_path.stat().st_size < 2000
    handler.close()
    log.removeHandler(handler)


def test_time_rollover_when_rolloverAt_in_past(tmp_path: Path) -> None:
    log_path = tmp_path / "earnie.log"
    log_path.write_text("seed-line\n", encoding="utf-8")
    handler = logger_config.SizeAndTimeRotatingFileHandler(
        str(log_path),
        when="W0",
        maxBytes=0,
        backupCount=8,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.rolloverAt = 1  # force time-based rollover
    log = logging.getLogger("test_time_rollover")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.propagate = False

    log.info("after-time-boundary")
    handler.flush()

    archives = _archive_siblings(log_path)
    assert len(archives) >= 1
    archive_text = archives[0].read_text(encoding="utf-8")
    assert "seed-line" in archive_text
    active = log_path.read_text(encoding="utf-8")
    assert "after-time-boundary" in active
    handler.close()
    log.removeHandler(handler)


def test_rename_fallback_copy_truncate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "earnie.log"
    log_path.write_text("before-rotate\n", encoding="utf-8")
    handler = logger_config.SizeAndTimeRotatingFileHandler(
        str(log_path),
        when="W0",
        maxBytes=0,
        backupCount=8,
        encoding="utf-8",
    )

    def _boom(src: str, dst: str) -> None:
        raise PermissionError("simulated lock")

    monkeypatch.setattr(os, "rename", _boom)
    handler.rolloverAt = 1
    log = logging.getLogger("test_rename_fallback")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.propagate = False
    handler.setFormatter(logging.Formatter("%(message)s"))

    log.info("after-fallback")
    handler.flush()

    archives = _archive_siblings(log_path)
    assert len(archives) >= 1
    assert "before-rotate" in archives[0].read_text(encoding="utf-8")
    assert "after-fallback" in log_path.read_text(encoding="utf-8")
    handler.close()
    log.removeHandler(handler)


def test_setup_logging_wires_size_and_time_handler(tmp_path: Path) -> None:
    log_path = tmp_path / "earnie.log"
    logger_config.setup_logging(log_file=str(log_path), level=logging.INFO)
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logger_config.SizeAndTimeRotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    handler = file_handlers[0]
    assert handler.maxBytes == logger_config._DEFAULT_MAX_BYTES
    assert handler.backupCount == logger_config._DEFAULT_BACKUP_COUNT
    assert handler.when == "W0"
