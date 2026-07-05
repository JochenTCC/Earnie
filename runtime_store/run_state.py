"""
run_state.py – Gemeinsamer Zustand des letzten main.py-Durchlaufs (nur main schreibt, app liest).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from typing import Any

from .file_metadata import RUN_STATE_SCHEMA, read_schema_version, stamp_payload

logger = logging.getLogger(__name__)

RUNTIME_DIR = os.environ.get("ENERGY_OPTIMIZER_RUNTIME_DIR", "runtime")
RUN_STATE_FILENAME = "optimizer_run_state.json"
RUN_STATE_FILE = os.path.join(RUNTIME_DIR, RUN_STATE_FILENAME)
LEGACY_RUN_STATE_PATH = RUN_STATE_FILENAME


def _candidate_paths() -> list[str]:
    return [RUN_STATE_FILE, LEGACY_RUN_STATE_PATH]


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_json(path: str, data: dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _save_atomic(path: str, data: dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    tmp = f"{path}.tmp"
    try:
        _write_json(tmp, data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _save_to_path(path: str, data: dict[str, Any]) -> None:
    """Atomar schreiben; bei EBUSY (Synology-Bind-Mount) direkt in die Zieldatei."""
    try:
        _save_atomic(path, data)
    except OSError as e:
        if e.errno != 16:
            raise
        logger.warning(
            "run_state: atomares Schreiben nach %s nicht möglich (%s), direkter Versuch",
            path,
            e,
        )
        _write_json(path, data)


def _is_unc_path(path: str) -> bool:
    return path.startswith("\\\\") or path.startswith("//")


def _load_json_from_path(path: str) -> dict[str, Any]:
    """JSON lesen; bei UNC-Pfaden Kopie über SMB-Client-Cache."""
    if _is_unc_path(path):
        fd, tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            shutil.copyfile(path, tmp)
            with open(tmp, "r", encoding="utf-8") as f:
                data = json.load(f)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not isinstance(data, dict):
            raise json.JSONDecodeError("root is not object", path, 0)
        return data
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("root is not object", path, 0)
    return data


def _load_from_path(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        data = _load_json_from_path(path)
        schema_version = read_schema_version(data, default=1)
        if schema_version > RUN_STATE_SCHEMA:
            logger.warning(
                "run_state: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                RUN_STATE_SCHEMA,
            )
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("run_state: Lesen von %s fehlgeschlagen: %s", path, e)
        return None


def save_run_state(payload: dict[str, Any], path: str | None = None) -> None:
    """Schreiben nach erfolgreichem main.py-Durchlauf (runtime-Verzeichnis mit Fallback)."""
    data = stamp_payload(
        {
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            **payload,
        },
        schema_version=RUN_STATE_SCHEMA,
    )
    targets = [path] if path else _candidate_paths()
    errors: list[str] = []

    for target in targets:
        try:
            _save_to_path(target, data)
            if target != targets[0]:
                logger.info("run_state: gespeichert unter %s", target)
            return
        except OSError as e:
            errors.append(f"{target}: {e}")

    message = "; ".join(errors)
    logger.error("run_state: Schreiben fehlgeschlagen: %s", message)
    raise OSError(message)


def load_run_state(path: str | None = None) -> dict[str, Any] | None:
    """Letzten main.py-Durchlauf laden; None wenn Datei fehlt oder ungültig."""
    if path:
        return _load_from_path(path)
    for candidate in _candidate_paths():
        state = _load_from_path(candidate)
        if state is not None:
            return state
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
