"""Shadow write block + shadow_writes.jsonl (§6.3)."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_store.shadow.mode import is_shadow_mode
from runtime_store.shadow.reader import read_latest

logger = logging.getLogger(__name__)

_lock = threading.Lock()
SHADOW_WRITES_NAME = "shadow_writes.jsonl"


def shadow_writes_path() -> Path:
    from runtime_store.persist_paths import runtime_dir

    return Path(runtime_dir()) / SHADOW_WRITES_NAME


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _current_cycle_seq() -> int | None:
    latest = read_latest()
    if not latest:
        return None
    try:
        return int(latest.get("cycle_seq"))
    except (TypeError, ValueError):
        return None


def log_would_write(
    *,
    backend: str,
    target: str,
    value: Any,
    source: str = "",
) -> None:
    """Append one would-write record and log INFO. Never raises."""
    if not is_shadow_mode():
        return
    try:
        entry = {
            "ts": _utc_iso(),
            "cycle_seq": _current_cycle_seq(),
            "backend": backend,
            "target": str(target),
            "value": value,
            "source": source or "",
        }
        path = shadow_writes_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        logger.info(
            "shadow: would write %s %s=%s%s",
            backend,
            target,
            value,
            f" ({source})" if source else "",
        )
    except Exception:  # noqa: BLE001
        logger.exception("shadow: failed to append shadow_writes.jsonl")


def read_shadow_writes(*, limit: int = 200) -> list[dict[str, Any]]:
    """Return the last *limit* would-write records (oldest first)."""
    path = shadow_writes_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    if limit > 0 and len(rows) > limit:
        return rows[-limit:]
    return rows


def block_write_if_shadow(
    *,
    backend: str,
    target: str,
    value: Any,
    source: str = "",
) -> bool:
    """
    If Shadow: log would-write and return True (caller must not send).

    Returns False when not in Shadow (proceed with real write).
    """
    if not is_shadow_mode():
        return False
    log_would_write(backend=backend, target=target, value=value, source=source)
    return True
