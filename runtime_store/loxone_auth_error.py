"""Persisted Loxone HTTP auth failure for main.py gate and Streamlit banner."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, TypedDict

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

AUTH_ERROR_FILENAME = "loxone_auth_error.json"


class LoxoneAuthErrorRecord(TypedDict):
    message: str
    http_status: int
    detected_at: str
    source: str


def auth_error_path() -> str:
    return runtime_path(AUTH_ERROR_FILENAME)


def persist_loxone_auth_error(
    *,
    message: str,
    http_status: int,
    source: str,
) -> None:
    path = auth_error_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload: LoxoneAuthErrorRecord = {
        "message": str(message),
        "http_status": int(http_status),
        "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(source),
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_loxone_auth_error() -> LoxoneAuthErrorRecord | None:
    path = auth_error_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid Loxone auth error file %s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    message = str(payload.get("message") or "").strip()
    if not message:
        return None
    try:
        http_status = int(payload.get("http_status") or 0)
    except (TypeError, ValueError):
        return None
    return LoxoneAuthErrorRecord(
        message=message,
        http_status=http_status,
        detected_at=str(payload.get("detected_at") or ""),
        source=str(payload.get("source") or ""),
    )


def clear_loxone_auth_error() -> None:
    path = auth_error_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning("Could not clear Loxone auth error file: %s", exc)


def needs_loxone_auth_recovery() -> bool:
    """True when Loxone backend has credentials but auth error file is set."""
    from integrations.ehal_live import is_loxone_backend
    from runtime_store.dotenv_io import loxone_credentials_configured

    if not is_loxone_backend():
        return False
    if not loxone_credentials_configured():
        return False
    return load_loxone_auth_error() is not None
