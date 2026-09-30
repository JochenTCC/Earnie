"""Shadow feed reader (latest.json / meta.json) with SMB-safe retry."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from runtime_store.shadow.feed import feed_dir

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_meta_cache: dict[str, Any] | None = None
_latest_cache: dict[str, Any] | None = None
_meta_mtime: float | None = None
_latest_mtime: float | None = None


def reset_reader_for_tests() -> None:
    global _meta_cache, _latest_cache, _meta_mtime, _latest_mtime
    with _lock:
        _meta_cache = None
        _latest_cache = None
        _meta_mtime = None
        _latest_mtime = None


def _read_json_retry(path: Path) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            text = path.read_text(encoding="utf-8")
            doc = json.loads(text)
            if not isinstance(doc, dict):
                raise ValueError(f"{path.name}: expected object")
            return doc
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(0.05)
                continue
            raise
    assert last_exc is not None
    raise last_exc


def read_meta(*, force: bool = False) -> dict[str, Any] | None:
    """Return meta.json or None if missing."""
    global _meta_cache, _meta_mtime
    path = feed_dir() / "meta.json"
    if not path.is_file():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _lock:
        if (
            not force
            and _meta_cache is not None
            and mtime is not None
            and mtime == _meta_mtime
        ):
            return dict(_meta_cache)
        try:
            doc = _read_json_retry(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("shadow: meta.json read failed: %s", exc)
            return _meta_cache
        _meta_cache = doc
        _meta_mtime = mtime
        return dict(doc)


def read_latest(*, force: bool = False) -> dict[str, Any] | None:
    """Return latest.json or None if missing."""
    global _latest_cache, _latest_mtime
    path = feed_dir() / "latest.json"
    if not path.is_file():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _lock:
        if (
            not force
            and _latest_cache is not None
            and mtime is not None
            and mtime == _latest_mtime
        ):
            return dict(_latest_cache)
        try:
            doc = _read_json_retry(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("shadow: latest.json read failed: %s", exc)
            return _latest_cache
        _latest_cache = doc
        _latest_mtime = mtime
        return dict(doc)


def records_map(latest: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = latest if latest is not None else read_latest()
    if not doc:
        return {}
    records = doc.get("records")
    return dict(records) if isinstance(records, dict) else {}
