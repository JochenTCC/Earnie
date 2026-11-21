"""Remove secrets from config documents before they leave the machine (support packages)."""
from __future__ import annotations

from typing import Any

REDACTED = "<entfernt>"
_SECRET_MARKERS = ("password", "passwort", "token", "secret", "api_key", "apikey")


def _is_secret_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def redact_secrets(value: Any) -> Any:
    """Copy of ``value`` with every non-empty string under a secret-looking key replaced."""
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if _is_secret_key(key) and isinstance(item, str) and item:
                out[key] = REDACTED
            else:
                out[key] = redact_secrets(item)
        return out
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value
