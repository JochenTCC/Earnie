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


def select_table_rows(at: AppTest, key_prefix: str, row_keys: list[str], *, timeout: float = 30.0) -> AppTest:
    """Wählt in der Tabelle mit dem Key ``key_prefix…`` die Zeilen mit diesen Index-Werten und führt die Seite aus.

    AppTest kann keine Tabellenzeile anklicken; die Auswahl wird als Widget-State
    (``{"selection": {"rows": [...], "columns": []}}``) gesetzt. Die Tabelle wird über
    die Zeilen-Keys im DataFrame-Index gefunden (Edibert-Übersicht: ``own:user_x``).
    """
    (key,) = [k for k in at.session_state.keys() if k.startswith(key_prefix)]  # noqa: SIM118 (kein __iter__)
    (frame,) = [f.value for f in at.dataframe if set(row_keys) <= set(f.value.index)]
    shown = list(frame.index)
    at.session_state[key] = {"selection": {"rows": [shown.index(r) for r in row_keys], "columns": []}}
    return at.run(timeout=timeout)
