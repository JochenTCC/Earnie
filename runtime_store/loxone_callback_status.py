"""Persist last inbound Miniserver HTTP callback (daemon → Streamlit).

The :8541 listener runs in ``main.py``; Streamlit is a separate process, so the
peer IP/time are written under ``runtime/`` for the UI to read.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

CALLBACK_FILENAME = "loxone_last_callback.json"


def _callback_path() -> str:
    return runtime_path(CALLBACK_FILENAME)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def record_loxone_callback(client_ip: str) -> None:
    """Atomically store last callback time (UTC ISO) and client IP."""
    ip = str(client_ip or "").strip() or "?"
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "client_ip": ip,
    }
    path = _callback_path()
    _ensure_parent(path)
    tmp = f"{path}.tmp"
    raw = json.dumps(payload, indent=2, ensure_ascii=False)
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(raw)
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("loxone callback status write failed: %s", exc)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(raw)
        except OSError as exc2:
            logger.warning("loxone callback status write failed: %s", exc2)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def load_loxone_callback_status() -> dict[str, Any] | None:
    """Return ``{ts, client_ip}`` or ``None`` if missing/invalid."""
    path = _callback_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    ts = str(data.get("ts") or "").strip()
    ip = str(data.get("client_ip") or "").strip()
    if not ts:
        return None
    return {"ts": ts, "client_ip": ip or "?"}


def format_loxone_callback_caption(
    status: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """German one-liner for SB / EHAL-Com (or „noch kein Aufruf“)."""
    data = status if status is not None else load_loxone_callback_status()
    if not data:
        return "Letzter Aufruf vom Miniserver: noch keiner (Port 8541)."
    try:
        ts = datetime.fromisoformat(str(data["ts"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return "Letzter Aufruf vom Miniserver: noch keiner (Port 8541)."
    ref = now if now is not None else datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    delta_sec = max(0, int((ref - ts).total_seconds()))
    minutes = delta_sec // 60
    ip = str(data.get("client_ip") or "?")
    if minutes < 1:
        age = "gerade eben"
    elif minutes == 1:
        age = "vor 1 min"
    else:
        age = f"vor {minutes} min"
    return f"Letzter Aufruf vom Miniserver: {age} von IP {ip}"
