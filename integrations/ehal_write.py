"""Publish EHAL write setpoints into the status.json ledger (2.7.q Q5).

``write_field`` records ``(qualified_id, value, published_at)`` only — it does not
call ``/dev/sps/io``. Loud Loxone writes use this ledger; the Miniserver VI polls
``status.json`` (push-only after Q5 cutover).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

PUBLISH_FILENAME = "ehal_published.json"

_lock = threading.Lock()
_published: dict[str, dict[str, Any]] = {}
_loaded = False


@dataclass(frozen=True)
class PublishRecord:
    """One published setpoint for status.json / write-trace."""

    qualified_id: str
    value: float
    published_at: str  # UTC ISO
    published: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualified_id": self.qualified_id,
            "value": self.value,
            "published_at": self.published_at,
            "published": self.published,
        }


def _publish_path() -> str:
    return runtime_path(PUBLISH_FILENAME)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load_from_disk() -> dict[str, dict[str, Any]]:
    path = _publish_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, raw in data.items():
        qid = str(key or "").strip()
        if not qid or not isinstance(raw, dict):
            continue
        try:
            value = float(raw.get("value"))
        except (TypeError, ValueError):
            continue
        published_at = str(raw.get("published_at") or "").strip()
        out[qid] = {"value": value, "published_at": published_at}
    return out


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        disk = _load_from_disk()
        if disk:
            _published.update(disk)
        _loaded = True


def _persist_unlocked() -> None:
    path = _publish_path()
    _ensure_parent(path)
    tmp = f"{path}.tmp"
    payload = {
        qid: {"value": entry["value"], "published_at": entry.get("published_at") or ""}
        for qid, entry in _published.items()
    }
    raw = json.dumps(payload, indent=2, ensure_ascii=False)
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(raw)
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("ehal publish persist failed: %s", exc)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(raw)
        except OSError as exc2:
            logger.warning("ehal publish persist failed: %s", exc2)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def write_field(qualified_id: str, value: float) -> PublishRecord:
    """Publish a setpoint into the status snapshot ledger (no Merker HTTP)."""
    qid = str(qualified_id or "").strip()
    published_at = datetime.now(timezone.utc).isoformat()
    if not qid:
        return PublishRecord(
            qualified_id="",
            value=float(value),
            published_at=published_at,
            published=False,
        )
    entry = {"value": float(value), "published_at": published_at}
    _ensure_loaded()
    with _lock:
        _published[qid] = entry
        _persist_unlocked()
    return PublishRecord(
        qualified_id=qid,
        value=float(value),
        published_at=published_at,
        published=True,
    )


def load_published() -> dict[str, float]:
    """Qualified ID → last published value."""
    _ensure_loaded()
    with _lock:
        return {qid: float(entry["value"]) for qid, entry in _published.items()}


def load_published_records() -> dict[str, dict[str, Any]]:
    """Qualified ID → ``{value, published_at}`` copy."""
    _ensure_loaded()
    with _lock:
        return {
            qid: {
                "value": float(entry["value"]),
                "published_at": str(entry.get("published_at") or ""),
            }
            for qid, entry in _published.items()
        }


def published_fetched_at() -> str | None:
    """Last Miniserver fetch time (global callback ``ts``), or ``None``."""
    from runtime_store.loxone_callback_status import load_loxone_callback_status

    status = load_loxone_callback_status()
    if not status:
        return None
    ts = str(status.get("ts") or "").strip()
    return ts or None


def clear_published_for_tests() -> None:
    """Test helper: empty in-memory ledger and drop the persist file."""
    global _loaded
    with _lock:
        _published.clear()
        _loaded = True
        path = _publish_path()
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
