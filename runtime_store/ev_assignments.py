"""Live EV ↔ wallbox assignments of the daemon and their files (multi-EV M3, D7).

- **Overlay:** the daemon installs the current assignments (EV id → wallbox id) with
  :func:`set_live_assignments`. :func:`apply_live_assignments` then gives every dynamic EV the
  view of its wallbox pair, or drops it while it is not assigned (it is not planned until
  then). Outside the daemon (UI, Scenario Explorer, tests) no overlay is installed and the
  loader view is returned unchanged.
- ``runtime/ev_assignments.json``: the engine's snapshot, written on every change, for the
  Monitor page and the cycle record. Never read back as truth: the daemon starts empty.
- ``runtime/ev_assignment_picks.json``: pick requests of the Monitor page (user evidence,
  D4 (d)); the daemon consumes them on its next tick.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

ASSIGNMENTS_FILENAME = "ev_assignments.json"
PICKS_FILENAME = "ev_assignment_picks.json"
SCHEMA_VERSION = 1

_lock = threading.Lock()
_live: dict[str, str] | None = None


def set_live_assignments(assignments: dict[str, str] | None) -> None:
    """Install the daemon's assignments (``None`` removes the overlay)."""
    global _live
    with _lock:
        _live = dict(assignments) if assignments is not None else None


def live_assignments() -> dict[str, str] | None:
    with _lock:
        return dict(_live) if _live is not None else None


def apply_live_assignments(consumers: list[dict]) -> list[dict]:
    """Consumers with the daemon's overlay applied to dynamic EVs (see module doc)."""
    from house_config.wallboxes import assigned_dynamic_ev_view, is_dynamic_ev

    current = live_assignments()
    if current is None:
        return consumers
    out: list[dict] = []
    for consumer in consumers:
        if str(consumer.get("type") or "") != "ev" or not is_dynamic_ev(consumer):
            out.append(consumer)
            continue
        wallbox_id = current.get(str(consumer.get("id") or ""))
        if wallbox_id:
            out.append(assigned_dynamic_ev_view(consumer, wallbox_id))
    return out


def _path(filename: str) -> str:
    from runtime_store.persist_paths_base import runtime_path

    return runtime_path(filename)


def _write_json_atomic(path: str, doc: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_assignments_snapshot(wallboxes: list[dict[str, Any]], *, updated_at: str) -> None:
    _write_json_atomic(
        _path(ASSIGNMENTS_FILENAME),
        {"schema_version": SCHEMA_VERSION, "updated_at": updated_at, "wallboxes": wallboxes},
    )


def read_assignments_snapshot() -> dict[str, Any] | None:
    """Last snapshot for display, or ``None`` when the daemon has not written one."""
    path = _path(ASSIGNMENTS_FILENAME)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path}: unbekanntes Format (schema_version {doc.get('schema_version')!r}).")
    return doc


def request_pick(wallbox_id: str, ev_id: str, session: str) -> None:
    """Append a pick request (Monitor page) for the daemon's next tick."""
    path = _path(PICKS_FILENAME)
    with _lock:
        picks = _read_picks(path)
        picks.append(
            {
                "wallbox_id": str(wallbox_id),
                "ev_id": str(ev_id),
                "session": str(session),
                "requested_at": _now_iso(),
            }
        )
        _write_json_atomic(path, picks)


def _read_picks(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, list):
        raise ValueError(f"{path}: muss eine Liste sein.")
    return [p for p in doc if isinstance(p, dict)]


def consume_picks() -> list[dict[str, Any]]:
    """Pick requests written since the last call; the file is removed."""
    path = _path(PICKS_FILENAME)
    with _lock:
        picks = _read_picks(path)
        if os.path.isfile(path):
            os.remove(path)
    return picks
