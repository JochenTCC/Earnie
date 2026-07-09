"""Stabile IDs aus Anzeigenamen (Hausprofile, Verbraucher, Planungs-Entitäten)."""
from __future__ import annotations

import re
import unicodedata

_UMLAUT_MAP = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "ae",
        "Ö": "oe",
        "Ü": "ue",
    }
)
_NON_ID_CHARS = re.compile(r"[^a-z0-9]+")


def slug_id(label: str, *, existing: set[str] | None = None) -> str:
    """Erzeugt eine eindeutige snake_case-ID aus einer Bezeichnung."""
    text = label.strip().translate(_UMLAUT_MAP).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_ID_CHARS.sub("_", text).strip("_")
    if not text:
        text = "eintrag"
    taken = set(existing or ())
    candidate = text
    suffix = 2
    while candidate in taken:
        candidate = f"{text}_{suffix}"
        suffix += 1
    return candidate
