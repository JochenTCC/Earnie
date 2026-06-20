"""
run_state.py – Gemeinsamer Zustand des letzten main.py-Durchlaufs (nur main schreibt, app liest).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from file_metadata import RUN_STATE_SCHEMA, read_schema_version, stamp_payload

logger = logging.getLogger(__name__)

RUN_STATE_FILE = "optimizer_run_state.json"


def _default_path() -> str:
    return RUN_STATE_FILE


def save_run_state(payload: dict[str, Any], path: str | None = None) -> None:
    """Atomares Schreiben nach erfolgreichem main.py-Durchlauf."""
    path = path or _default_path()
    data = stamp_payload(
        {
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            **payload,
        },
        schema_version=RUN_STATE_SCHEMA,
    )
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logger.error("run_state: Schreiben fehlgeschlagen: %s", e)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def load_run_state(path: str | None = None) -> dict[str, Any] | None:
    """Letzten main.py-Durchlauf laden; None wenn Datei fehlt oder ungültig."""
    path = path or _default_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        schema_version = read_schema_version(data, default=1)
        if schema_version > RUN_STATE_SCHEMA:
            logger.warning(
                "run_state: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                RUN_STATE_SCHEMA,
            )
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("run_state: Lesen fehlgeschlagen: %s", e)
        return None


def completed_at_epoch(state: dict[str, Any] | None) -> float | None:
    """Unix-Zeitstempel des letzten Durchlaufs."""
    if not state:
        return None
    raw = state.get("completed_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).timestamp()
    except ValueError:
        return None


def age_seconds(state: dict[str, Any] | None) -> float | None:
    epoch = completed_at_epoch(state)
    if epoch is None:
        return None
    return max(0.0, datetime.now().timestamp() - epoch)
