"""Optimizer daemon heartbeat for container HEALTHCHECK (2.6.m / H4)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from runtime_store.persist_paths import runtime_path

HEARTBEAT_FILENAME = "daemon_heartbeat.json"
STALE_AFTER_SEC = 180


def heartbeat_path() -> Path:
    return Path(runtime_path(HEARTBEAT_FILENAME))


def touch_daemon_heartbeat(*, now_ts: float | None = None) -> Path:
    """Write/refresh ``runtime/daemon_heartbeat.json`` with a Unix timestamp."""
    path = heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": int(now_ts if now_ts is not None else time.time())}
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def read_heartbeat_ts(path: Path | None = None) -> int | None:
    target = path if path is not None else heartbeat_path()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("ts")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def heartbeat_is_fresh(
    *,
    now_ts: float | None = None,
    stale_after_sec: int = STALE_AFTER_SEC,
    path: Path | None = None,
) -> bool:
    ts = read_heartbeat_ts(path)
    if ts is None:
        return False
    now = int(now_ts if now_ts is not None else time.time())
    return (now - ts) <= stale_after_sec
