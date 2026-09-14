"""Phone vs desktop S-2 chart span (24h segments vs SA₀→SA₂)."""
from __future__ import annotations

import re

import streamlit as st

from data.planning_window import ChartSpan

SESSION_S2_SPAN_OVERRIDE = "s2_span_override"

# Phones only — tablets (iPad, Android tablet) keep the desktop full span.
_PHONE_UA_RE = re.compile(
    r"(iphone|ipod|android.*mobile|windows phone|blackberry|bb10|opera mini|"
    r"iemobile|mobile.*firefox|webos)",
    re.IGNORECASE,
)


def is_phone_user_agent(user_agent: str) -> bool:
    """True for phone UAs; tablets and desktops return False."""
    return bool(_PHONE_UA_RE.search(user_agent or ""))


def _request_user_agent() -> str:
    try:
        headers = getattr(st.context, "headers", None)
    except Exception:
        return ""
    if headers is None:
        return ""
    if hasattr(headers, "get"):
        return str(headers.get("User-Agent") or headers.get("user-agent") or "")
    return ""


def _query_span_override() -> ChartSpan | None:
    try:
        params = st.query_params
    except Exception:
        return None
    raw = params.get("s2_span")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw in ("segment", "full"):
        return raw  # type: ignore[return-value]
    return None


def resolve_s2_span() -> ChartSpan:
    """
    Desktop/tablet → ``full`` (SA₀→SA₂); phone → ``segment`` (24h switch).

    Overrides (highest first): ``?s2_span=segment|full``, session
    ``s2_span_override``, then User-Agent.
    """
    query = _query_span_override()
    if query is not None:
        return query
    session_val = st.session_state.get(SESSION_S2_SPAN_OVERRIDE)
    if session_val in ("segment", "full"):
        return session_val
    if is_phone_user_agent(_request_user_agent()):
        return "segment"
    return "full"


def set_s2_span_override(span: ChartSpan | None) -> None:
    """Test/helper: pin span in session, or clear with None."""
    if span is None:
        st.session_state.pop(SESSION_S2_SPAN_OVERRIDE, None)
        return
    if span not in ("segment", "full"):
        raise ValueError(f"span muss 'segment' oder 'full' sein, erhalten: {span!r}.")
    st.session_state[SESSION_S2_SPAN_OVERRIDE] = span
