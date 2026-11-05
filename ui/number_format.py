"""Euro and cent amounts in the viewer's browser language, on top of ``edibert.i18n.numbers``.

Streamlit renders on the server, so the container locale says nothing about the viewer.
The ``Accept-Language`` header of the request does: Edibert picks the supported language
(``en`` / ``de``) the browser prefers most. Without a header (AppTest, scripts) or when the
header names neither language, Earnie uses ``de``, because its UI is German.

Scope (decided 2026-11-05): euro and cent amounts. kWh, kW and % keep the point for now.
The units are Earnie's own wording (``€``, ``Cent/kWh``).
"""
from __future__ import annotations

import streamlit as st
from edibert.i18n import numbers

UI_LANGUAGE = "de"


def _request_accept_language() -> str | None:
    try:
        headers = getattr(st.context, "headers", None)
    except Exception:
        return None
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get("Accept-Language") or headers.get("accept-language")
    return str(value) if value else None


def viewer_language() -> str:
    """``en`` or ``de`` for the current viewer; ``de`` when the browser names neither."""
    return numbers.language_from_accept_language(_request_accept_language()) or UI_LANGUAGE


def decimal_separator() -> str:
    return numbers.decimal_separator(viewer_language())


def format_decimal(value: float, digits: int = 2, *, signed: bool = False) -> str:
    """``value`` with ``digits`` decimals and the viewer's separator; ``signed`` adds ``+``."""
    return numbers.format_fixed(value, digits, viewer_language(), signed=signed)


def format_euro(euro: float, digits: int = 2, *, signed: bool = False) -> str:
    return f"{format_decimal(euro, digits, signed=signed)} €"


def format_cent_kwh(cent: float, digits: int = 2, *, signed: bool = False) -> str:
    return f"{format_decimal(cent, digits, signed=signed)} Cent/kWh"


def plotly_separators() -> str:
    """Plotly ``layout.separators`` for the viewer."""
    return numbers.plotly_separators(viewer_language())
