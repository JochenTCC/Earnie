"""Inbox for Loxone Virtual Output pushes (spike/vo-push-pilot → push-only read path).

The :8541 listener and the optimizer read path share one process (``main.py``).
``record_push`` updates an in-process cache used by ``read_push_value``; the JSON
file under ``runtime/`` is for the Streamlit UI (separate process).

A Virtual Output command (repeated, default 10 s) calls
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

from ehal.qualified_ids import (
    DIGITAL_KINDS,
    field_kind,
    id_namespace_alternation,
    is_digital_id,
)
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
# Daemon in-process view (listener + read path). JSON file is for the UI process.
_memory: dict[str, dict[str, Any]] = {}
# Last usable numeric value per ID (for the 5-minute hold on required fields).
_last_known: dict[str, tuple[float, datetime]] = {}


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
        _memory.clear()
        _last_known.clear()
        try:
            os.remove(_inbox_path())
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("loxone push inbox clear failed: %s", exc)


def reset_memory_for_tests() -> None:
    """Clear in-process cache only (unit tests)."""
    with _lock:
        _memory.clear()
        _last_known.clear()


def hydrate_memory_from_disk() -> None:
    """Load JSON into the in-process cache once (daemon start)."""
    with _lock:
        if _memory:
            return
        rows = load_inbox()
        _memory.update(rows)
        for ehal_id, row in rows.items():
            if row.get("parse_ok", True) and row.get("value") is not None:
                ts = _parse_ts(row.get("last_ts")) or datetime.now(timezone.utc)
                _last_known[ehal_id] = (float(row["value"]), ts)


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
        rows = dict(_memory) if _memory else load_inbox()
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
        _memory[ehal_id] = dict(row)
        if value is not None:
            _last_known[ehal_id] = (float(value), stamp)
        _write_inbox(rows)
    if is_new:
        logger.info("loxone push inbox: new signal %s (peer %s)", ehal_id, row["peer"])
    return "new" if is_new else "ok"


def memory_snapshot() -> dict[str, dict[str, Any]]:
    """Copy of the in-process inbox (daemon); falls back to disk when empty."""
    with _lock:
        if _memory:
            return {k: dict(v) for k, v in _memory.items()}
    return load_inbox()


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
DEFAULT_REPEAT_S = 10.0
# Hold last known value this long after silence / link loss before a read error.
LAST_KNOWN_MAX_S = 300.0
STARTUP_WAIT_MAX_S = 40.0

# Powers: silence while link alive → assume 0 (analog VO has no Off command).
POWER_KINDS = frozenset(
    {
        "sens_power_act",
        "sens_ess_power",
        "sens_ess_charge_power",
        "sens_ess_discharge_power",
        "sens_evcs_active_power",
        "sens_grid_power_active",
        "sens_pv_production_active",
        "sens_power_consumers",
    }
)

STATE_LAST_KNOWN = "Zuletzt bekannt (gehalten)"
STATE_READ_ERROR = "Lesefehler"


def expected_repeat_s() -> float:
    """Configured VO repeat interval in seconds (default 10)."""
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
# stale limit (3 x repeat, default 30 s at 10 s repeat).

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


def _is_energy_kind(kind: str) -> bool:
    """Cumulative kWh counters — never invent 0 when silent (Q6)."""
    return "energy" in str(kind or "")


def derive_state(
    ehal_id: str,
    row: dict[str, Any] | None,
    *,
    link: bool,
    repeat_s: float | None = None,
    now: datetime | None = None,
) -> tuple[str, float | None]:
    """(state label, derived value) for one expected signal; ``row`` is ``None`` if never received."""
    energy = _is_energy_kind(field_kind(ehal_id))
    if row is None:
        if energy:
            return (STATE_UNKNOWN, None)
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
    if energy:
        return (STATE_READ_ERROR, None)
    return (STATE_ZERO_ASSUMED_SILENT, 0.0) if link else (STATE_UNKNOWN, None)


def _is_power_kind(kind: str) -> bool:
    return kind in POWER_KINDS or (kind.startswith("sens_") and "power" in kind)


def _hold_last_known(
    held: tuple[float, datetime] | None,
    *,
    now: datetime,
    max_age_s: float = LAST_KNOWN_MAX_S,
) -> tuple[str, float | None]:
    if held is None:
        return (STATE_READ_ERROR, None)
    value, stamp = held
    age = (now - stamp).total_seconds()
    if age <= max_age_s:
        return (STATE_LAST_KNOWN, float(value))
    return (STATE_READ_ERROR, None)


def resolve_push_read(
    ehal_id: str,
    row: dict[str, Any] | None,
    *,
    link: bool,
    repeat_s: float | None = None,
    now: datetime | None = None,
    last_known: tuple[float, datetime] | None = None,
    last_known_max_s: float = LAST_KNOWN_MAX_S,
) -> tuple[str, float | None]:
    """Resolve a push signal for the optimizer read path (zero rule + 5 min last-known).

    Returns ``(state, value)``. ``value is None`` means a read error for the caller.
    """
    ref = now if now is not None else datetime.now(timezone.utc)
    kind = field_kind(ehal_id)
    digital = kind in DIGITAL_KINDS
    power = _is_power_kind(kind)
    energy = _is_energy_kind(kind)
    held = last_known

    def hold() -> tuple[str, float | None]:
        return _hold_last_known(held, now=ref, max_age_s=last_known_max_s)

    if row is not None and row.get("parse_ok", True) and row.get("value") is not None:
        value = float(row["value"])
        if value == 0.0:
            return (STATE_ZERO_HELD, 0.0) if link else (STATE_ZERO_HELD_NO_LINK, 0.0)
        if not is_stale(row, repeat_s=repeat_s, now=ref):
            return (STATE_OK, value)
        if digital:
            return (STATE_DIGITAL_HELD, value)
        if energy:
            return (STATE_READ_ERROR, None)
        if power and link:
            return (STATE_ZERO_ASSUMED_SILENT, 0.0)
        return hold()

    if row is not None and (not row.get("parse_ok", True) or row.get("value") is None):
        if energy:
            return (STATE_READ_ERROR, None)
        return hold()

    if energy:
        return (STATE_READ_ERROR, None)
    if digital and link:
        return (STATE_ZERO_ASSUMED_NEVER, 0.0)
    if power and link:
        return (STATE_ZERO_ASSUMED_NEVER, 0.0)
    return hold()


def read_push_value(
    ehal_id: str,
    *,
    now: datetime | None = None,
    repeat_s: float | None = None,
) -> tuple[float | None, str]:
    """Optimizer-facing read: ``(value, state)`` from the in-process inbox.

    ``value is None`` → treat like a failed Merker poll (required fields abort upstream).
    """
    eid = str(ehal_id or "").strip()
    if not eid or not is_valid_ehal_id(eid):
        return None, STATE_READ_ERROR
    ref = now if now is not None else datetime.now(timezone.utc)
    with _lock:
        signals = dict(_memory) if _memory else load_inbox()
        row = signals.get(eid)
        link = link_alive(signals, repeat_s=repeat_s, now=ref)
        state, value = resolve_push_read(
            eid,
            row,
            link=link,
            repeat_s=repeat_s,
            now=ref,
            last_known=_last_known.get(eid),
        )
        if value is not None and state in (
            STATE_ZERO_ASSUMED_SILENT,
            STATE_ZERO_ASSUMED_NEVER,
            STATE_OK,
            STATE_ZERO_HELD,
            STATE_DIGITAL_HELD,
        ):
            _last_known[eid] = (float(value), ref)
    return value, state


def read_push_counter(
    ehal_id: str,
    *,
    now: datetime | None = None,
    repeat_s: float | None = None,
) -> float | None:
    """Fresh cumulative counter from the inbox, or ``None`` when missing/stale.

    Never invents ``0`` for silence (Q6 meter energy). A fresh explicit ``0.0``
    push is returned as ``0.0``.
    """
    eid = str(ehal_id or "").strip()
    if not eid or not is_valid_ehal_id(eid):
        return None
    ref = now if now is not None else datetime.now(timezone.utc)
    with _lock:
        signals = dict(_memory) if _memory else load_inbox()
        row = signals.get(eid)
        if row is None:
            return None
        if not row.get("parse_ok", True) or row.get("value") is None:
            return None
        if is_stale(row, repeat_s=repeat_s, now=ref):
            return None
        return float(row["value"])


def read_push_ready_by_time(
    ehal_id: str,
    *,
    now: datetime | None = None,
    repeat_s: float | None = None,
    last_known_max_s: float = LAST_KNOWN_MAX_S,
) -> str | float | None:
    """FertigUm from the inbox: numeric (Unix/Loxone epoch) or fresh raw text.

    Never invents ``0`` as a deadline. Stale/missing → last-known numeric within the
    hold window, else ``None``. Non-numeric ``raw`` is returned only while fresh.
    """
    eid = str(ehal_id or "").strip()
    if not eid or not is_valid_ehal_id(eid):
        return None
    ref = now if now is not None else datetime.now(timezone.utc)
    with _lock:
        signals = dict(_memory) if _memory else load_inbox()
        row = signals.get(eid)
        held = _last_known.get(eid)
        if row is not None and not is_stale(row, repeat_s=repeat_s, now=ref):
            if row.get("parse_ok", True) and row.get("value") is not None:
                return float(row["value"])
            raw = str(row.get("raw") or "").strip()
            if raw:
                return raw
        state, value = _hold_last_known(held, now=ref, max_age_s=last_known_max_s)
        if state == STATE_LAST_KNOWN and value is not None:
            return float(value)
    return None


def wait_for_push_link(
    *,
    timeout_s: float = STARTUP_WAIT_MAX_S,
    poll_s: float = 0.5,
    now_fn=None,
    sleep_fn=None,
) -> bool:
    """Block until ``link_alive`` or ``timeout_s``. Returns True when the link is up."""
    import time as _time

    sleep = sleep_fn or _time.sleep
    clock = now_fn or (lambda: datetime.now(timezone.utc))
    deadline = clock().timestamp() + float(timeout_s)
    while clock().timestamp() < deadline:
        signals = memory_snapshot()
        if link_alive(signals, now=clock()):
            logger.info("loxone push: link alive (heartbeat/analog) before first run")
            return True
        sleep(poll_s)
    logger.warning(
        "loxone push: no link within %.0fs — continuing (reads may use last-known / errors)",
        timeout_s,
    )
    return False


_link_was_alive: bool | None = None


def log_link_transition(*, now: datetime | None = None) -> None:
    """Emit a log line when the Miniserver push link appears or drops."""
    global _link_was_alive
    ref = now if now is not None else datetime.now(timezone.utc)
    alive = link_alive(memory_snapshot(), now=ref)
    if _link_was_alive is None:
        _link_was_alive = alive
        return
    if alive and not _link_was_alive:
        logger.warning("loxone push: link restored")
    elif not alive and _link_was_alive:
        logger.warning("loxone push: link lost (no fresh non-zero push within stale limit)")
    _link_was_alive = alive
