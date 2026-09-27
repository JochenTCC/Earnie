"""Transport replay from Prod feed (§6.1)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from runtime_store.env_vars import read_env
from runtime_store.shadow.mode import is_shadow_mode
from runtime_store.shadow.reader import read_latest, read_meta, records_map

logger = logging.getLogger(__name__)

_DEFAULT_MAX_AGE_SEC = 120
_MISSING_LOG_INTERVAL_SEC = 3600
_missing_log_last: dict[str, float] = {}
_lock = threading.Lock()


def reset_replay_for_tests() -> None:
    with _lock:
        _missing_log_last.clear()


def max_age_sec() -> int:
    raw = read_env("SHADOW_MAX_AGE_SEC")
    if not raw:
        return _DEFAULT_MAX_AGE_SEC
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_AGE_SEC


def _parse_utc(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _log_missing(key: str, reason: str) -> None:
    now = time.monotonic()
    with _lock:
        last = _missing_log_last.get(key, 0.0)
        if now - last < _MISSING_LOG_INTERVAL_SEC:
            return
        _missing_log_last[key] = now
    logger.warning("shadow: no feed value for %s (%s)", key, reason)


def is_record_stale(record: dict[str, Any], *, ref_ts: str | None) -> bool:
    """Stale when record is older than *ref_ts* (or wall clock) by more than max age.

    Prefer ``latest.json`` ``cycle_ts`` as *ref_ts*: Prod sampler flushes advance
    ``heartbeat_ts`` without refreshing IO timestamps, which falsely stale'd
    cycle-fresh values when age was measured vs heartbeat.
    Records newer than the ref (e.g. mid-wait sampler updates) stay fresh.
    """
    rec_ts = _parse_utc(record.get("ts") if isinstance(record, dict) else None)
    if rec_ts is None:
        return True
    ref = _parse_utc(ref_ts) or datetime.now(timezone.utc)
    age = (ref - rec_ts).total_seconds()
    return age > max_age_sec()


def _staleness_ref_ts(latest: dict[str, Any] | None, meta: dict[str, Any] | None) -> str | None:
    """Prefer cycle_ts; fall back to heartbeat_ts for older feeds."""
    if isinstance(latest, dict):
        cycle_ts = latest.get("cycle_ts")
        if isinstance(cycle_ts, str) and cycle_ts.strip():
            return cycle_ts
    if isinstance(meta, dict):
        heartbeat = meta.get("heartbeat_ts")
        if isinstance(heartbeat, str) and heartbeat.strip():
            return heartbeat
    return None


def lookup_record(key: str) -> dict[str, Any] | None:
    """Return fresh ok/error record for *key*, or None if missing/stale."""
    if not is_shadow_mode():
        return None
    latest = read_latest()
    meta = read_meta()
    records = records_map(latest)
    record = records.get(key)
    if not isinstance(record, dict):
        _log_missing(key, "missing")
        return None
    ref_ts = _staleness_ref_ts(
        latest if isinstance(latest, dict) else None,
        meta if isinstance(meta, dict) else None,
    )
    if is_record_stale(record, ref_ts=ref_ts):
        _log_missing(key, "stale")
        return None
    return record


def replay_loxone_io(key: str) -> str | None:
    """Replay ``loxone:io:*`` → raw LL.value string or None (unreachable)."""
    record = lookup_record(key)
    if record is None or not record.get("ok"):
        return None
    payload = record.get("payload")
    if isinstance(payload, dict):
        raw = (payload.get("LL") or {}).get("value", "")
        if raw is None or str(raw).strip() == "":
            return None
        return str(raw).strip()
    return None


def replay_loxone_io_all(key: str) -> dict | None:
    """Replay ``loxone:io_all:*`` → LL dict or None."""
    record = lookup_record(key)
    if record is None or not record.get("ok"):
        return None
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else None


def replay_ha_get(key: str) -> Any:
    """
    Replay ``ha:get:*``.

    Returns payload on success. Raises ``HaHttpError`` on missing/failed
    (same as live adapter).
    """
    from integrations.ha_adapter import HaHttpError

    record = lookup_record(key)
    if record is None:
        raise HaHttpError(f"HA GET failed: shadow feed missing for {key}")
    if not record.get("ok"):
        status = record.get("status")
        err = record.get("error") or "shadow feed error"
        raise HaHttpError(
            f"HA GET failed: {err}",
            status_code=int(status) if status is not None else None,
        )
    return record.get("payload")


def replay_openems_get(key: str) -> dict[str, Any] | None:
    """
    Replay ``openems:get:*`` → payload dict.

    Raises ``OpenemsHttpError`` on missing/failed.
    """
    from integrations.openems_adapter import OpenemsHttpError

    record = lookup_record(key)
    if record is None:
        raise OpenemsHttpError(f"OpenEMS GET failed: shadow feed missing for {key}")
    if not record.get("ok"):
        status = record.get("status")
        err = record.get("error") or "shadow feed error"
        raise OpenemsHttpError(
            f"OpenEMS GET failed: {err}",
            status_code=int(status) if status is not None else None,
        )
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else None


def replay_ext_payload(key: str) -> Any | None:
    """Return ext:* payload if fresh and ok; else None (caller may fall back)."""
    record = lookup_record(key)
    if record is None or not record.get("ok"):
        return None
    return record.get("payload")


def assert_not_shadow_backend(action: str) -> None:
    """Raise if Shadow tries non-replayable backend access."""
    if not is_shadow_mode():
        return
    from runtime_store.shadow.errors import ShadowBackendAccessError

    raise ShadowBackendAccessError(
        f"Shadow Mode: backend access not allowed ({action})"
    )
