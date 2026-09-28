"""Prod shadow feed: in-memory latest map, JSONL archive, atomic meta/latest."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_store.env_vars import read_env
from runtime_store.shadow.mode import is_shadow_mode

logger = logging.getLogger(__name__)

FEED_SCHEMA = 1
_WARN_INTERVAL_SEC = 15 * 60
_DEFAULT_RETENTION_DAYS = 14

_lock = threading.RLock()
_latest: dict[str, Any] = {}
_cycle_keys: set[str] = set()
_cycle_seq = 0
_jsonl_dirty = False
_warn_last: dict[str, float] = {}
_shadow_warned = False


def reset_for_tests() -> None:
    """Clear in-memory feed state (unit tests only)."""
    global _cycle_seq, _jsonl_dirty, _shadow_warned
    with _lock:
        _latest.clear()
        _cycle_keys.clear()
        _cycle_seq = 0
        _jsonl_dirty = False
        _warn_last.clear()
        _shadow_warned = False


def feed_dir() -> Path:
    override = read_env("SHADOW_FEED_PATH")
    if override:
        return Path(override)
    from runtime_store.persist_paths import config_dir

    return Path(config_dir()) / "shadow_feed"


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _rate_limited_warn(cause: str, message: str, *args: Any) -> None:
    now = time.monotonic()
    last = _warn_last.get(cause, 0.0)
    if now - last < _WARN_INTERVAL_SEC:
        return
    _warn_last[cause] = now
    logger.warning(message, *args)


def is_feed_recording_enabled() -> bool:
    """True when Prod opted in and this process is not Shadow."""
    global _shadow_warned
    try:
        import config

        enabled = bool(config.is_shadow_feed_enabled())
    except Exception:  # noqa: BLE001 — never break callers
        return False
    if not enabled:
        return False
    if is_shadow_mode():
        if not _shadow_warned:
            _shadow_warned = True
            logger.warning(
                "shadow_feed_enabled ignored: EARNIE_SHADOW=1 "
                "(recorder is Prod-only)"
            )
        return False
    return True


def retention_days() -> int:
    try:
        import config

        return int(config.get_shadow_feed_retention_days())
    except Exception:  # noqa: BLE001
        return _DEFAULT_RETENTION_DAYS


def keys_seen_this_cycle() -> frozenset[str]:
    with _lock:
        return frozenset(_cycle_keys)


def record(
    key: str,
    *,
    ok: bool,
    payload: Any = None,
    status: int | None = None,
    error: str | None = None,
    ts: str | None = None,
) -> None:
    """Append one record to memory + JSONL. Never raises to caller."""
    if not is_feed_recording_enabled():
        return
    try:
        entry = {
            "key": key,
            "ts": ts or _utc_iso(),
            "ok": bool(ok),
            "status": status,
            "payload": payload,
            "error": error,
        }
        with _lock:
            _latest[key] = entry
            _cycle_keys.add(key)
            _append_jsonl_unlocked(entry)
    except Exception as exc:  # noqa: BLE001
        _rate_limited_warn("record", "shadow feed record failed: %s", exc)


def _append_jsonl_unlocked(entry: dict[str, Any]) -> None:
    global _jsonl_dirty
    directory = feed_dir()
    directory.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = directory / f"feed-{day}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    _jsonl_dirty = True


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _meta_payload(*, cycle_seq: int, heartbeat_ts: str) -> dict[str, Any]:
    from runtime_store.data_model import CURRENT_DATA_MODEL
    from runtime_store.persist_paths import runtime_dir
    from version import __version__

    ehal_backend = ""
    try:
        import config

        ehal_backend = str(config.get("EHAL_BACKEND") or "")
    except Exception:  # noqa: BLE001
        pass
    return {
        "feed_schema": FEED_SCHEMA,
        "earnie_version": __version__,
        "earnie_data_model": CURRENT_DATA_MODEL,
        "ehal_backend": ehal_backend,
        "prod_runtime_dir": str(Path(runtime_dir()).resolve()),
        "heartbeat_ts": heartbeat_ts,
        "cycle_seq": cycle_seq,
    }


def flush_latest(*, bump_cycle: bool = False) -> None:
    """Write atomic latest.json (+ meta). Optionally bump cycle_seq."""
    if not is_feed_recording_enabled():
        return
    directory: Path | None = None
    try:
        with _lock:
            global _cycle_seq
            if bump_cycle:
                _cycle_seq += 1
                _cycle_keys.clear()
            seq = _cycle_seq
            heartbeat = _utc_iso()
            latest_doc = {
                "cycle_seq": seq,
                "cycle_ts": heartbeat if bump_cycle else _latest_cycle_ts(seq),
                "records": dict(_latest),
            }
            directory = feed_dir()
            _atomic_write_json(directory / "latest.json", latest_doc)
            _atomic_write_json(
                directory / "meta.json",
                _meta_payload(cycle_seq=seq, heartbeat_ts=heartbeat),
            )
    except Exception as exc:  # noqa: BLE001
        _rate_limited_warn("flush", "shadow feed flush failed: %s", exc)
    if bump_cycle and directory is not None:
        try:
            with _lock:
                _prune_retention_unlocked(directory)
        except Exception as exc:  # noqa: BLE001
            _rate_limited_warn("prune", "shadow feed prune failed: %s", exc)


def _latest_cycle_ts(seq: int) -> str | None:
    """Keep previous cycle_ts on sampler flush when seq unchanged."""
    path = feed_dir() / "latest.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if int(doc.get("cycle_seq") or 0) == seq:
            return doc.get("cycle_ts")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return None


def _prune_retention_unlocked(directory: Path) -> None:
    days = max(1, retention_days())
    cutoff = datetime.now(timezone.utc).date().toordinal() - days
    for path in directory.glob("feed-*.jsonl"):
        stem = path.stem  # feed-YYYY-MM-DD
        try:
            date_part = stem.removeprefix("feed-")
            year, month, day = (int(x) for x in date_part.split("-"))
            ordinal = datetime(year, month, day, tzinfo=timezone.utc).date().toordinal()
        except (ValueError, TypeError):
            continue
        if ordinal < cutoff:
            try:
                path.unlink()
            except OSError as exc:
                _rate_limited_warn("prune", "shadow feed prune failed: %s", exc)


def flush_after_cycle() -> None:
    """Bump cycle_seq and flush after a completed ``main()`` call."""
    flush_latest(bump_cycle=True)


def flush_after_sampler() -> None:
    """Heartbeat flush after a successful sampler tick (no cycle_seq bump)."""
    flush_latest(bump_cycle=False)
