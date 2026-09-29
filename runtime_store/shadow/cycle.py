"""Shadow cycle timing vs Prod feed (§6.2)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from runtime_store.shadow.mode import is_shadow_mode
from runtime_store.shadow.reader import read_latest, read_meta, records_map

logger = logging.getLogger(__name__)

_CYCLE_WAIT_SEC = 60
_HEARTBEAT_STALE_SEC = 5 * 60
_TRIGGER_KEY = "trigger:request_optimize"

_last_consumed_cycle_seq: int = 0
_last_trigger_ts: str | None = None
_feed_lag: bool = False
_skip_reason: str | None = None


def reset_cycle_for_tests() -> None:
    global _last_consumed_cycle_seq, _last_trigger_ts, _feed_lag, _skip_reason
    _last_consumed_cycle_seq = 0
    _last_trigger_ts = None
    _feed_lag = False
    _skip_reason = None


def feed_lag() -> bool:
    return _feed_lag


def skip_reason() -> str | None:
    return _skip_reason


def last_consumed_cycle_seq() -> int:
    return _last_consumed_cycle_seq


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


def heartbeat_age_sec() -> float | None:
    meta = read_meta(force=True)
    if not meta:
        return None
    hb = _parse_utc(meta.get("heartbeat_ts"))
    if hb is None:
        return None
    return abs((datetime.now(timezone.utc) - hb).total_seconds())


def is_feed_heartbeat_stale() -> bool:
    age = heartbeat_age_sec()
    if age is None:
        return True
    return age > _HEARTBEAT_STALE_SEC


def feed_health() -> dict[str, Any]:
    """Snapshot for UI banner / status."""
    meta = read_meta(force=True) or {}
    latest = read_latest(force=True) or {}
    age = heartbeat_age_sec()
    stale = is_feed_heartbeat_stale()
    return {
        "prod_version": meta.get("earnie_version"),
        "prod_data_model": meta.get("earnie_data_model"),
        "ehal_backend": meta.get("ehal_backend"),
        "cycle_seq": latest.get("cycle_seq", meta.get("cycle_seq")),
        "cycle_ts": latest.get("cycle_ts"),
        "heartbeat_ts": meta.get("heartbeat_ts"),
        "heartbeat_age_sec": age,
        "stale": stale,
        "feed_lag": _feed_lag,
        "skip_reason": _skip_reason,
        "last_consumed_cycle_seq": _last_consumed_cycle_seq,
    }


def wait_for_prod_cycle(*, timeout_sec: float = _CYCLE_WAIT_SEC) -> dict[str, Any]:
    """
    Wait up to *timeout_sec* for a newer ``cycle_seq``.

    Sets ``feed_lag`` when timeout expires with no newer cycle.
    Sets skip when heartbeat is stale (caller should skip the cycle).
    """
    global _last_consumed_cycle_seq, _feed_lag, _skip_reason

    _feed_lag = False
    _skip_reason = None
    if not is_shadow_mode():
        return {"skipped": False, "feed_lag": False}

    if is_feed_heartbeat_stale():
        _skip_reason = "prod_feed_stale"
        logger.warning(
            "shadow: Prod feed stale (heartbeat > %ss) — skipping cycle",
            _HEARTBEAT_STALE_SEC,
        )
        return {"skipped": True, "feed_lag": False, "reason": _skip_reason}

    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while True:
        latest = read_latest(force=True) or {}
        try:
            seq = int(latest.get("cycle_seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if seq > _last_consumed_cycle_seq:
            _last_consumed_cycle_seq = seq
            _feed_lag = False
            return {
                "skipped": False,
                "feed_lag": False,
                "cycle_seq": seq,
                "cycle_ts": latest.get("cycle_ts"),
            }
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)

    # No newer cycle within timeout — run with latest (may be stale values)
    _feed_lag = True
    latest = read_latest(force=True) or {}
    try:
        seq = int(latest.get("cycle_seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    if seq > 0:
        _last_consumed_cycle_seq = seq
    logger.info(
        "shadow: no new cycle_seq within %ss — running with feed_lag=true (seq=%s)",
        timeout_sec,
        seq,
    )
    return {
        "skipped": False,
        "feed_lag": True,
        "cycle_seq": seq,
        "cycle_ts": latest.get("cycle_ts"),
    }


def consume_optimize_trigger() -> bool:
    """
    True once when feed has a newer ``trigger:request_optimize`` event.

    Mirrors Prod's out-of-band optimize request.
    """
    global _last_trigger_ts
    if not is_shadow_mode():
        return False
    records = records_map(read_latest(force=True))
    record = records.get(_TRIGGER_KEY)
    if not isinstance(record, dict):
        return False
    ts = str(record.get("ts") or "")
    if not ts or ts == _last_trigger_ts:
        return False
    _last_trigger_ts = ts
    logger.info("shadow: mirrored trigger:request_optimize from feed (ts=%s)", ts)
    return True
