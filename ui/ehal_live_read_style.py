"""Live-Lesen row colouring (EHAL-Com Phase B).

Colour is additive; Status text remains the accessibility source of truth.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ehal.qualified_ids import field_kind
from integrations.loxone_ehal_mapping import TELEMETRY_OPTIONAL, TELEMETRY_REQUIRED

# CSS colours (light theme; Styler text color).
_COLOR_DEFAULT = ""
_COLOR_OPTIONAL = "#6b7280"  # gray
_COLOR_CACHED = "#1d4ed8"  # blue
_COLOR_STALE = "#ca8a04"  # yellow/amber
_COLOR_ERROR = "#b91c1c"  # red

_CACHED_STATES = {
    "Zuletzt bekannt (gehalten)",
    "0 (gehalten)",
    "0 (gehalten, Verbindung unbekannt)",
    "Digital (gehalten)",
}
_STALE_STATES = {
    "0 angenommen (verstummt)",
    "0 angenommen (nie gesendet)",
    "Warnung",
}
_ERROR_STATES = {
    "Kein Mapping",
    "Lesefehler",
    "Fehler",
    "Nicht lesbar",
    "Unbekannt (keine Verbindung)",
    "Fehlt",
}

_OPTIONAL_KINDS = frozenset(TELEMETRY_OPTIONAL)
_REQUIRED_KINDS = frozenset(TELEMETRY_REQUIRED)

_OPTIONAL_FALLBACK_HINT = "optional — no live value (optimizer uses config defaults)"


def is_optional_live_read(ehal_id: str) -> bool:
    """True when the field kind is optional plant telemetry (not required)."""
    kind = field_kind(ehal_id)
    if kind in _REQUIRED_KINDS:
        return False
    if kind in _OPTIONAL_KINDS:
        return True
    # Role-required false for get_* / sens_* not in the required plant set.
    try:
        from ehal.field_registry import loxone_spec

        spec = loxone_spec(kind)
        if spec is not None and not spec.read_required and kind.startswith(
            ("get_", "sens_")
        ):
            return kind not in _REQUIRED_KINDS
    except Exception:  # noqa: BLE001
        pass
    return False


def live_read_text_color(status: str, *, optional: bool) -> str:
    """Map Status (+ optional flag) to a CSS color string (empty = default)."""
    state = str(status or "").strip()
    if state in _ERROR_STATES:
        return _COLOR_ERROR
    if state in _STALE_STATES or state.startswith("Warnung"):
        return _COLOR_STALE
    if state in _CACHED_STATES:
        return _COLOR_CACHED
    if optional and state not in _ERROR_STATES:
        return _COLOR_OPTIONAL
    return _COLOR_DEFAULT


def apply_optional_fallback_hint(row: dict[str, str]) -> dict[str, str]:
    """Attach a Detail hint for optional rows with no live value."""
    field = str(row.get("EHAL-Feld") or "")
    if not is_optional_live_read(field):
        return row
    wert = str(row.get("Wert") or "").strip()
    ehal = str(row.get("Wert (EHAL)") or "").strip()
    has_wert = bool(wert) and wert != "—"
    has_ehal = bool(ehal) and ehal != "—"
    if has_wert or has_ehal:
        return row
    status = str(row.get("Status") or "")
    if status in _ERROR_STATES and status != "Kein Mapping":
        return row
    out = dict(row)
    detail = str(out.get("Detail") or "").strip()
    if _OPTIONAL_FALLBACK_HINT not in detail:
        out["Detail"] = (
            f"{detail}; {_OPTIONAL_FALLBACK_HINT}" if detail else _OPTIONAL_FALLBACK_HINT
        )
    return out


def style_live_read_rows(rows: list[dict[str, str]]) -> pd.io.formats.style.Styler:
    """Pandas Styler: colour entire rows by Live-Lesen state."""
    prepared = [apply_optional_fallback_hint(r) for r in rows]
    df = pd.DataFrame(prepared)
    if df.empty:
        return df.style

    colors: list[str] = []
    for _, row in df.iterrows():
        optional = is_optional_live_read(str(row.get("EHAL-Feld") or ""))
        colors.append(live_read_text_color(str(row.get("Status") or ""), optional=optional))

    def _row_style(series: pd.Series) -> list[str]:
        idx = int(series.name) if series.name is not None else 0
        color = colors[idx] if 0 <= idx < len(colors) else ""
        if not color:
            return [""] * len(series)
        return [f"color: {color}"] * len(series)

    return df.style.apply(_row_style, axis=1)
