"""EHAL write-error persistence and write-trace rows (split from ``ehal_live``)."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from ehal import EhalWriteError, validate_write_error
from runtime_store.persist_paths import runtime_path

# Keep the historic logger name so log filters keep working after the split.
logger = logging.getLogger("integrations.ehal_live")

WRITE_ERROR_FILENAME = "ehal_write_error.json"

SKIPPED_MESSAGE = "Übersprungen: Funktion nicht verfügbar (Mapping unvollständig)"


def write_error_path() -> str:
    return runtime_path(WRITE_ERROR_FILENAME)


def persist_write_error(error: EhalWriteError | None) -> None:
    path = write_error_path()
    if error is None:
        clear_write_error()
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(dict(error), handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clear_write_error() -> None:
    path = write_error_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning("Could not clear EHAL write error file: %s", exc)


def load_write_error() -> EhalWriteError | None:
    path = write_error_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return validate_write_error(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid EHAL write error file %s: %s", path, exc)
        return None


def _last_skipped(adapter: Any) -> list[str]:
    getter = getattr(adapter, "last_skipped_fields", None)
    return list(getter()) if callable(getter) else []


def _last_unconfigured(adapter: Any) -> list[str]:
    getter = getattr(adapter, "last_unconfigured_fields", None)
    return list(getter()) if callable(getter) else []


def build_ehal_write_records(
    fields: dict[str, float],
    *,
    written_at: str,
    error: EhalWriteError | None,
    skipped: list[str] | None = None,
    unconfigured: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Compact write trace rows for optimizer_run_state.ehal_writes.

    ``unconfigured`` fields were never activated: nothing was written, so no row
    (a "success" row for a field that never left Earnie would be wrong).
    """
    failed = set(error.get("failed_fields") or []) if error else set()
    message = str(error.get("message") or "") if error else ""
    skipped_set = set(skipped or [])
    unconfigured_set = set(unconfigured or [])
    rows: list[dict[str, Any]] = []
    for field, value in fields.items():
        if field in unconfigured_set:
            continue
        if field in skipped_set:
            rows.append(
                {
                    "field": field,
                    "value": value,
                    "success": False,
                    "skipped": True,
                    "written_at": written_at,
                    "message": SKIPPED_MESSAGE,
                }
            )
            continue
        if error is None:
            ok = True
        elif failed:
            ok = field not in failed
        else:
            ok = False
        rows.append(
            {
                "field": field,
                "value": value,
                "success": ok,
                "written_at": written_at,
                "message": "" if ok else message,
            }
        )
    return rows
