"""Decimal separator for amounts in the UI, from the viewer's browser language.

Streamlit renders on the server, so the container locale says nothing about the viewer.
The ``Accept-Language`` header of the request does: its first language decides.
Languages that write a decimal point get ``.``, every other language gets ``,``.
Without a header (AppTest, scripts) the separator is ``,``, because the UI is German.

Scope (decided 2026-11-05): euro and cent amounts. kWh, kW and % keep the point for now.
"""
from __future__ import annotations

import streamlit as st

DECIMAL_COMMA = ","
DECIMAL_POINT = "."

# Primary language subtags whose convention is a decimal point (CLDR).
_POINT_LANGUAGES = frozenset(
    {"en", "ja", "zh", "ko", "he", "th", "hi", "ga", "mt", "ms", "fil", "tl", "sw"}
)


def decimal_separator_for_accept_language(header: str | None) -> str:
    """``,`` or ``.`` for the first language of an ``Accept-Language`` header."""
    if not header:
        return DECIMAL_COMMA
    first = header.split(",", 1)[0].split(";", 1)[0].strip()
    primary = first.split("-", 1)[0].split("_", 1)[0].lower()
    if not primary or primary == "*":
        return DECIMAL_COMMA
    return DECIMAL_POINT if primary in _POINT_LANGUAGES else DECIMAL_COMMA


def _request_accept_language() -> str | None:
    try:
        headers = getattr(st.context, "headers", None)
    except Exception:
        return None
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get("Accept-Language") or headers.get("accept-language")
    return str(value) if value else None


def decimal_separator() -> str:
    """The separator for the current viewer."""
    return decimal_separator_for_accept_language(_request_accept_language())


def format_decimal(value: float, digits: int = 2, *, signed: bool = False) -> str:
    """``value`` with ``digits`` decimals and the viewer's separator; ``signed`` adds ``+``."""
    text = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    separator = decimal_separator()
    return text if separator == DECIMAL_POINT else text.replace(".", separator)


def format_euro(euro: float, digits: int = 2, *, signed: bool = False) -> str:
    return f"{format_decimal(euro, digits, signed=signed)} €"


def plotly_separators() -> str:
    """Plotly ``layout.separators``: decimal mark first, then the thousands mark."""
    return ",." if decimal_separator() == DECIMAL_COMMA else ".,"


def format_cent_kwh(cent: float, digits: int = 2, *, signed: bool = False) -> str:
    return f"{format_decimal(cent, digits, signed=signed)} Cent/kWh"
