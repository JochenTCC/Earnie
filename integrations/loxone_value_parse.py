"""Parse Loxone Merker values returned as strings (often with units)."""
from __future__ import annotations

import math


def parse_binary_value(raw) -> bool | None:
    """Convert a Loxone Merker to True/False; None on read/parse failure."""
    if raw is None:
        return None
    try:
        return int(round(float(raw))) == 1
    except (TypeError, ValueError):
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
