"""Shadow-feed mirror and overlay for Loxone push reads (split from loxone_push_inbox)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from runtime_store.loxone_push_parse import (
    HEARTBEAT_ID,
    SHADOW_FEED_SOURCE,
    parse_push_value,
)


def _shadow_feed_key(ehal_id: str) -> str:
    return f"loxone:io:{ehal_id}"


def _record_push_to_shadow_feed(ehal_id: str, text: str, *, parse_ok: bool) -> None:
    """Prod: mirror VO push into the shadow feed (never raises)."""
    try:
        from runtime_store.shadow.hooks import record_transport

        record_transport(
            _shadow_feed_key(ehal_id),
            ok=parse_ok,
            payload={"LL": {"value": text}},
            error=None if parse_ok else "parse_failed",
        )
    except Exception:  # noqa: BLE001 — recorder must never break Prod
        pass


def _inbox_row_from_shadow_feed(ehal_id: str) -> dict[str, Any] | None:
    """Shadow: inbox-shaped row from ``loxone:io:<id>``, or None if missing/stale.

    Does not warn on miss — callers warn if the feed has no row for *ehal_id*.
    """
    try:
        from runtime_store.shadow.mode import is_shadow_mode
        from runtime_store.shadow.replay import lookup_record

        if not is_shadow_mode():
            return None
        record = lookup_record(_shadow_feed_key(ehal_id), log_missing=False)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    raw = ""
    if isinstance(payload, dict):
        raw = str((payload.get("LL") or {}).get("value") or "").strip()
    elif payload is not None:
        raw = str(payload).strip()
    if not raw:
        if record.get("ok"):
            return None
        return {
            "value": None,
            "raw": "",
            "parse_ok": False,
            "last_ts": record.get("ts"),
            "count": 1,
            "source": SHADOW_FEED_SOURCE,
        }
    value = parse_push_value(raw)
    return {
        "value": value,
        "raw": raw,
        "parse_ok": value is not None,
        "last_ts": record.get("ts")
        or datetime.now(timezone.utc).isoformat(),
        "count": 1,
        "source": SHADOW_FEED_SOURCE,
    }


def _shadow_feed_signals_for_read(ehal_id: str) -> dict[str, dict[str, Any]]:
    """Feed rows for *ehal_id* (+ heartbeat). Feed-only — no Prod-inbox file."""
    out: dict[str, dict[str, Any]] = {}
    for key_id in (ehal_id, HEARTBEAT_ID):
        row = _inbox_row_from_shadow_feed(key_id)
        if row is not None:
            out[key_id] = row
    if ehal_id not in out:
        try:
            from runtime_store.shadow.replay import warn_missing_feed_key

            warn_missing_feed_key(_shadow_feed_key(ehal_id), "missing")
        except Exception:  # noqa: BLE001
            pass
    return out


def _shadow_feed_overlay_if_active(ehal_id: str) -> dict[str, dict[str, Any]]:
    """Shadow-only: feed rows for *ehal_id*; else ``{}``."""
    try:
        from runtime_store.shadow.mode import is_shadow_mode

        if is_shadow_mode():
            return _shadow_feed_signals_for_read(ehal_id)
    except Exception:  # noqa: BLE001
        return {}
    return {}
