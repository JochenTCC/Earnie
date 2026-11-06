"""Numbers in the viewer's browser language, on top of ``edibert.i18n.numbers``.

Streamlit renders on the server, so the container locale says nothing about the viewer.
The ``Accept-Language`` header of the request does: Edibert picks the supported language
(``en`` / ``de``) the browser prefers most. Without a header (AppTest, scripts) or when the
header names neither language, Earnie uses ``de``, because its UI is German.

Three paths, one per way a number reaches the screen:

* Text built on the server: ``format_decimal`` / ``format_general`` and the amount helpers.
  The units are Earnie's own wording (``€``, ``Cent/kWh``, ``kWh``).
* Plotly: ``localized_figure`` around every figure passed to ``st.plotly_chart``.
* Numeric table columns: ``edibert.ui.number_columns.localized_number_column``. The browser
  formats them by its own locale, so a browser in neither language can differ from the text.

``st.number_input`` is not covered: Streamlit writes its printf format with a point.
"""
from __future__ import annotations

import plotly.graph_objects as go
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


def format_general(value: float) -> str:
    """``value`` as ``:g`` writes it (no trailing zeros), with the viewer's separator."""
    return numbers.format_general(value, viewer_language())


def format_euro(euro: float, digits: int = 2, *, signed: bool = False) -> str:
    return f"{format_decimal(euro, digits, signed=signed)} €"


def format_cent_kwh(cent: float, digits: int = 2, *, signed: bool = False) -> str:
    return f"{format_decimal(cent, digits, signed=signed)} Cent/kWh"


def plotly_separators() -> str:
    """Plotly ``layout.separators`` for the viewer."""
    return numbers.plotly_separators(viewer_language())


def localized_figure(fig: go.Figure) -> go.Figure:
    """``fig`` with the viewer's separators, for hovers, axes and text templates."""
    fig.update_layout(separators=plotly_separators())
    return fig
