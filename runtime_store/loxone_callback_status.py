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


def _load_raw(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def record_loxone_callback(client_ip: str, *, status_json: bool = False) -> None:
    """Atomically store last callback time (UTC ISO) and client IP.

    ``status_json=True`` marks a ``status.json`` fetch: ``status_json_ts`` is
    the proof that the hub actually polled the setpoints (incl.
    ``heartbeat_earnie``). Other callbacks (heartbeat push) keep the previous
    ``status_json_ts``.
    """
    ip = str(client_ip or "").strip() or "?"
    now = datetime.now(timezone.utc).isoformat()
    path = _callback_path()
    payload: dict[str, Any] = {"ts": now, "client_ip": ip}
    if status_json:
        payload["status_json_ts"] = now
    else:
        previous = str(_load_raw(path).get("status_json_ts") or "").strip()
        if previous:
            payload["status_json_ts"] = previous
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
    """Return ``{ts, client_ip, status_json_ts}`` or ``None`` if missing/invalid.

    ``status_json_ts`` is ``None`` until the hub fetched ``status.json``.
    """
    data = _load_raw(_callback_path())
    ts = str(data.get("ts") or "").strip()
    ip = str(data.get("client_ip") or "").strip()
    if not ts:
        return None
    status_json_ts = str(data.get("status_json_ts") or "").strip()
    return {"ts": ts, "client_ip": ip or "?", "status_json_ts": status_json_ts or None}


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
