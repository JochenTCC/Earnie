"""Parse Loxone Merker values returned as strings (often with units)."""
from __future__ import annotations

import math


_BINARY_TRUE = frozenset({"on", "true", "away", "1", "yes"})
_BINARY_FALSE = frozenset({"off", "false", "home", "0", "no"})


def parse_binary_value(raw) -> bool | None:
    """Convert a live backend value to True/False; None on read/parse failure.

    Accepts numeric 0/1 (Loxone/OpenEMS) and common HA state strings
    (on/off, true/false, home/away), case-insensitive.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        try:
            return int(round(float(raw))) == 1
        except (TypeError, ValueError, OverflowError):
            return None
    text = str(raw).strip()
    if not text:
        return None
    # Strip trailing unit suffixes (e.g. Loxone "1.0").
    lowered = text.lower()
    if lowered in _BINARY_TRUE:
        return True
    if lowered in _BINARY_FALSE:
        return False
    try:
        return int(round(float(text.split()[0]))) == 1
    except (TypeError, ValueError, OverflowError, IndexError):
        return None


def parse_text_value(raw) -> str | None:
    """Normalize a Loxone text value; None on read failure."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None


def parse_analog_value(raw) -> float | None:
    """Convert a Loxone measurement to float; None on read/parse failure."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return round(value, 2)
