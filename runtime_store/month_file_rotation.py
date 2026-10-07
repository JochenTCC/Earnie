"""Monthly file rotation helpers (shared by earnie.log and optimization_history.jsonl)."""
from __future__ import annotations

import logging
import os
import re
import shutil
import time

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_COUNT = 12
ARCHIVE_SUFFIX = "%Y-%m-%d_%H-%M-%S"
ARCHIVE_EXT_MATCH = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(\.\d+)?(\.\w+)?$",
    re.ASCII,
)


def compute_next_month_rollover(now: float | int) -> float:
    """Unix timestamp of the next local month start (day 1, 00:00)."""
    lt = time.localtime(int(now))
    year, month = lt.tm_year, lt.tm_mon
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    return time.mktime((year, month, 1, 0, 0, 0, -1, -1, -1))


def list_rotated_siblings(path: str) -> list[str]:
    """Archive siblings of *path*, oldest first (name sort)."""
    directory = os.path.dirname(path) or "."
    base = os.path.basename(path)
    prefix = base + "."
    if not os.path.isdir(directory):
        return []
    found: list[str] = []
    for name in os.listdir(directory):
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix) :]
        if not ARCHIVE_EXT_MATCH.match(suffix):
            continue
        full = os.path.join(directory, name)
        if os.path.isfile(full):
            found.append(full)
    found.sort()
    return found


def unique_archive_path(path: str, when: float | int | None = None) -> str:
    """Stamped archive path that does not yet exist."""
    stamp = time.strftime(ARCHIVE_SUFFIX, time.localtime(int(when or time.time())))
    candidate = f"{path}.{stamp}"
    if not os.path.exists(candidate):
        return candidate
    n = 1
    while os.path.exists(f"{candidate}.{n}"):
        n += 1
    return f"{candidate}.{n}"


def rotate_file(source: str, dest: str) -> None:
    """Rename *source* to *dest*; on failure copy then truncate *source*."""
    if not os.path.exists(source):
        return
    try:
        os.rename(source, dest)
        return
    except OSError as rename_exc:
        try:
            shutil.copy2(source, dest)
            with open(source, "w", encoding="utf-8", newline="\n"):
                pass
        except OSError as copy_exc:
            logger.warning(
                "File rollover failed for %s -> %s (rename: %s; copy: %s)",
                source,
                dest,
                rename_exc,
                copy_exc,
            )
            raise copy_exc from rename_exc


def prune_archives(path: str, backup_count: int) -> None:
    """Delete oldest archives beyond *backup_count*."""
    if backup_count <= 0:
        return
    siblings = list_rotated_siblings(path)
    excess = len(siblings) - backup_count
    if excess <= 0:
        return
    for old in siblings[:excess]:
        try:
            os.remove(old)
        except OSError as exc:
            logger.warning("Could not remove archive %s: %s", old, exc)


def maybe_rollover(
    path: str,
    *,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    rollover_at: float,
) -> tuple[float, bool]:
    """
    If now >= rollover_at, archive non-empty *path* and prune.

    Returns (next_rollover_at, did_rotate).
    """
    now = time.time()
    if now < rollover_at:
        return rollover_at, False
    next_at = compute_next_month_rollover(now)
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return next_at, False
    dest = unique_archive_path(path, when=now)
    rotate_file(path, dest)
    prune_archives(path, backup_count)
    return next_at, True
