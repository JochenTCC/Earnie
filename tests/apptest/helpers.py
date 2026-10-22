"""Kleine Helfer für die Interaktions- und Logiktests (Ebene 1)."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_MESSAGE_KINDS = ("success", "error", "warning", "info", "caption")


def click(at: AppTest, key_or_label: str, *, timeout: float = 30.0) -> AppTest:
    """Klickt den Button mit diesem ``key`` (sonst mit diesem Label) und führt die Seite aus."""
    try:
        button = at.button(key=key_or_label)
    except KeyError:
        button = next(b for b in at.button if b.label == key_or_label)
    return button.click().run(timeout=timeout)


def messages(at: AppTest) -> dict[str, list[str]]:
    """Sichtbare Meldungen nach Art (success, error, warning, info, caption)."""
    return {kind: [e.value for e in getattr(at, kind)] for kind in _MESSAGE_KINDS}


def assert_clean(at: AppTest) -> None:
    """Keine Exception auf der Seite; sonst die Meldung im Assertion-Text."""
    assert not at.exception, [e.value for e in at.exception]


def file_snapshot(path: str | Path) -> bytes | None:
    """Dateiinhalt als Bytes, ``None`` wenn die Datei fehlt (Vergleich "unverändert")."""
    target = Path(path)
    return target.read_bytes() if target.exists() else None
