"""Pilot (spike/vo-push-pilot): inbox for Loxone Virtual Output pushes.

Observation only — nothing here feeds the optimizer. The :8541 listener runs in
``main.py``; Streamlit is a separate process, so the inbox is persisted under
``runtime/`` for the UI to read (same pattern as ``loxone_callback_status``).

A Virtual Output command (repeated, e.g. every 30 s) calls
``GET /ehal/loxone/telemetry/<EHAL-ID>/<value>``; the EHAL ID travels in the
path, so no Merker name is needed to learn which signal this is.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

from ehal.qualified_ids import id_namespace_alternation, is_digital_id
from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

INBOX_FILENAME = "loxone_push_inbox.json"
MAX_IDS = 200
MAX_RAW_LEN = 32
HEARTBEAT_ID = "heartbeat"  # constant non-zero push that proves the Miniserver link
# Loxone pushes measurements (sens_*) and inputs (get_*) only; never setpoints.
_ID_PATTERN = re.compile(
    r"^(?:" + HEARTBEAT_ID + r"|(?:(?:" + id_namespace_alternation()
    + r")\.[a-z0-9_]{1,64}\.)?(?:sens|get)_[a-z0-9_]{1,64})$"
)
_UNIT_SUFFIXES = ("kWh", "kW", "W", "%", "°C", "A", "h")
_EMA_MIN_S = 0.5
_EMA_MAX_S = 3600.0
_EMA_WEIGHT = 0.3

_lock = threading.Lock()


def is_valid_ehal_id(ehal_id: object) -> bool:
    return bool(_ID_PATTERN.match(str(ehal_id or "")))


def parse_push_value(raw: object) -> float | None:
    """Parse a pushed value; ``None`` when empty, too long or not finite."""
    text = str(raw if raw is not None else "").strip().replace(",", ".")
    if not text or len(text) > MAX_RAW_LEN:
        return None
    for suffix in _UNIT_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _inbox_path() -> str:
    return runtime_path(INBOX_FILENAME)


def load_inbox() -> dict[str, dict[str, Any]]:
    """Return ``{ehal_id: row}``; empty dict if the file is missing or invalid."""
    path = _inbox_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    rows = data.get("signals") if isinstance(data, dict) else None
    return {str(k): v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def clear_inbox() -> None:
    """Delete all stored pushes (pilot button)."""
    with _lock:
        try:
            os.remove(_inbox_path())
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("loxone push inbox clear failed: %s", exc)


def _write_inbox(rows: dict[str, dict[str, Any]]) -> None:
    path = _inbox_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    raw = json.dumps({"signals": rows}, indent=2, ensure_ascii=False)
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(raw)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("loxone push inbox write failed: %s", exc)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def record_push(
    ehal_id: str,
    raw: str,
    peer: str = "",
    *,
    now: datetime | None = None,
) -> str:
    """Store one push. Returns ``"ok"``, ``"new"`` (first time this ID), or a reject reason.

    Reject reasons: ``"bad_id"``, ``"bad_raw"`` (empty/oversized), ``"full"`` (ID cap).
    """
    if not is_valid_ehal_id(ehal_id):
        return "bad_id"
    text = str(raw if raw is not None else "").strip()
    if not text or len(text) > MAX_RAW_LEN:
        return "bad_raw"
    stamp = now if now is not None else datetime.now(timezone.utc)
    with _lock:
        rows = load_inbox()
        row = rows.get(ehal_id)
        is_new = row is None
        if is_new:
            if len(rows) >= MAX_IDS:
                return "full"
            row = {"first_ts": stamp.isoformat(), "count": 0, "interval_ema_s": None}
        value = parse_push_value(text)
        previous = _parse_ts(row.get("last_ts"))
        if previous is not None:
            delta = (stamp - previous).total_seconds()
            if _EMA_MIN_S <= delta <= _EMA_MAX_S:
                ema = row.get("interval_ema_s")
                row["interval_ema_s"] = round(
                    delta if ema is None else (1 - _EMA_WEIGHT) * float(ema) + _EMA_WEIGHT * delta,
                    2,
                )
        row.update(
            {
                "raw": text,
                "value": value,
                "parse_ok": value is not None,
                "last_ts": stamp.isoformat(),
                "count": int(row.get("count") or 0) + 1,
                "peer": str(peer or "").strip() or "?",
            }
        )
        rows[ehal_id] = row
        _write_inbox(rows)
    if is_new:
        logger.info("loxone push inbox: new signal %s (peer %s)", ehal_id, row["peer"])
    return "new" if is_new else "ok"


def _parse_ts(value: object) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def age_seconds(row: dict[str, Any], *, now: datetime | None = None) -> float | None:
    """Seconds since the last push, or ``None`` if unknown."""
    last = _parse_ts(row.get("last_ts"))
    if last is None:
        return None
    ref = now if now is not None else datetime.now(timezone.utc)
    return max(0.0, (ref - last).total_seconds())


REPEAT_ENV = "EARNIE_PILOT_PUSH_REPEAT_S"
DEFAULT_REPEAT_S = 30.0


def expected_repeat_s() -> float:
    """Configured VO repeat interval in seconds (pilot default 30)."""
    try:
        value = float(os.getenv(REPEAT_ENV) or DEFAULT_REPEAT_S)
    except ValueError:
        return DEFAULT_REPEAT_S
    return value if value > 0 else DEFAULT_REPEAT_S


def is_stale(
    row: dict[str, Any],
    *,
    factor: float = 3.0,
    repeat_s: float | None = None,
    now: datetime | None = None,
) -> bool:
    """True when the last push is older than ``factor`` × the configured repeat interval.

    Not based on ``interval_ema_s``: changes arrive between repeats, so the smoothed
    gap is shorter than the repeat interval and would flag quiet signals as stale.
    """
    age = age_seconds(row, now=now)
    if age is None:
        return False
    limit = float(repeat_s) if repeat_s else expected_repeat_s()
    return age > factor * limit


# --- Derived value state ---------------------------------------------------------------
# A Loxone output reports "On" (value != 0) and "Off" (value == 0) separately. An analog
# output has no Off command, so nothing is sent at 0; a digital output sends its Off
# command once on the edge, not repeated. So a silent analog signal means 0 *if the link
# is alive*; the link is judged from repeating non-zero signals (the heartbeat, or any
# fresh analog value). A drop to 0 of an analog signal is therefore noticed only after the
# stale limit (3 x repeat, default 90 s).

STATE_OK = "OK"
STATE_ZERO_HELD = "0 (gehalten)"
STATE_ZERO_HELD_NO_LINK = "0 (gehalten, Verbindung unbekannt)"
STATE_DIGITAL_HELD = "Digital (gehalten)"
STATE_ZERO_ASSUMED_SILENT = "0 angenommen (verstummt)"
STATE_ZERO_ASSUMED_NEVER = "0 angenommen (nie gesendet)"
STATE_UNKNOWN = "Unbekannt (keine Verbindung)"
STATE_UNREADABLE = "Nicht lesbar"


def link_alive(
    signals: dict[str, dict[str, Any]],
    *,
    repeat_s: float | None = None,
    now: datetime | None = None,
) -> bool:
    """True when a repeating non-zero signal arrived recently (heartbeat or analog value)."""
    for ehal_id, row in signals.items():
        if is_digital_id(ehal_id):
            continue  # edge-based, its age says nothing about the link
        value = row.get("value")
        if value is None or float(value) == 0.0:
            continue
        if not is_stale(row, repeat_s=repeat_s, now=now):
            return True
    return False


def derive_state(
    ehal_id: str,
    row: dict[str, Any] | None,
    *,
    link: bool,
    repeat_s: float | None = None,
    now: datetime | None = None,
) -> tuple[str, float | None]:
    """(state label, derived value) for one expected signal; ``row`` is ``None`` if never received."""
    if row is None:
        return (STATE_ZERO_ASSUMED_NEVER, 0.0) if link else (STATE_UNKNOWN, None)
    if not row.get("parse_ok", True) or row.get("value") is None:
        return (STATE_UNREADABLE, None)
    value = float(row["value"])
    if value == 0.0:
        # explicit Off message: held until the next message; the link cannot confirm it
        return (STATE_ZERO_HELD, 0.0) if link else (STATE_ZERO_HELD_NO_LINK, 0.0)
    if not is_stale(row, repeat_s=repeat_s, now=now):
        return (STATE_OK, value)
    if is_digital_id(ehal_id):
        return (STATE_DIGITAL_HELD, value)  # edge-complete (On and Off commands)
    return (STATE_ZERO_ASSUMED_SILENT, 0.0) if link else (STATE_UNKNOWN, None)
