"""Unit tests for MonthRotatingFileHandler / setup_logging rotation."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

import logger_config
from runtime_store.month_file_rotation import compute_next_month_rollover


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


def test_large_file_does_not_size_rollover(tmp_path: Path) -> None:
    log_path = tmp_path / "earnie.log"
    handler = logger_config.MonthRotatingFileHandler(
        str(log_path),
        backupCount=12,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    # Keep rollover in the future so only a size trigger would rotate.
    handler.rolloverAt = int(time.time()) + 3600
    log = logging.getLogger("test_no_size_rollover")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.propagate = False

    for i in range(80):
        log.info("payload-%s-%s", i, "x" * 80)
    handler.flush()

    assert not _archive_siblings(log_path)
    assert log_path.stat().st_size > 2000
    handler.close()
    log.removeHandler(handler)


def test_time_rollover_when_rolloverAt_in_past(tmp_path: Path) -> None:
    log_path = tmp_path / "earnie.log"
    log_path.write_text("seed-line\n", encoding="utf-8")
    handler = logger_config.MonthRotatingFileHandler(
        str(log_path),
        backupCount=12,
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
    handler = logger_config.MonthRotatingFileHandler(
        str(log_path),
        backupCount=12,
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


def test_backup_count_prunes_to_twelve(tmp_path: Path) -> None:
    log_path = tmp_path / "earnie.log"
    for i in range(14):
        stamp = f"2025-{i + 1:02d}-01_00-00-00" if i < 12 else f"2026-{(i - 11):02d}-01_00-00-00"
        (tmp_path / f"earnie.log.{stamp}").write_text(f"old-{i}\n", encoding="utf-8")
    log_path.write_text("active\n", encoding="utf-8")
    handler = logger_config.MonthRotatingFileHandler(
        str(log_path),
        backupCount=12,
        encoding="utf-8",
    )
    handler.rolloverAt = 1
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("test_prune")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.propagate = False
    log.info("after-prune")
    handler.flush()
    archives = _archive_siblings(log_path)
    assert len(archives) == 12
    handler.close()
    log.removeHandler(handler)


def test_compute_next_month_rollover_is_day_one() -> None:
    # Mid-January 2026 local — next boundary is 2026-02-01 00:00
    mid = time.mktime((2026, 1, 15, 12, 0, 0, -1, -1, -1))
    next_at = compute_next_month_rollover(mid)
    lt = time.localtime(next_at)
    assert (lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, lt.tm_min, lt.tm_sec) == (
        2026,
        2,
        1,
        0,
        0,
        0,
    )


def test_setup_logging_wires_month_handler(tmp_path: Path) -> None:
    log_path = tmp_path / "earnie.log"
    logger_config.setup_logging(log_file=str(log_path), level=logging.INFO)
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logger_config.MonthRotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    handler = file_handlers[0]
    assert handler.backupCount == logger_config._DEFAULT_BACKUP_COUNT
    assert logger_config._DEFAULT_BACKUP_COUNT == 12
    assert handler.rolloverAt == int(compute_next_month_rollover(time.time()))
    assert os.path.isabs(handler.baseFilename)


def test_setup_logging_resolves_relative_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    logger_config.setup_logging(log_file="earnie.log", level=logging.INFO)
    root = logging.getLogger()
    handler = next(
        h for h in root.handlers if isinstance(h, logger_config.MonthRotatingFileHandler)
    )
    assert handler.baseFilename == str((tmp_path / "earnie.log").resolve())
