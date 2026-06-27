"""Navigation zwischen Live-Ansicht und 24h-Historie-Schritten."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from runtime_store import history_timeline

SESSION_OFFSET_KEY = "history_offset_days"


def get_history_offset_days() -> int:
    """0 = Live; 1 = letzter vergangener 24h-Tag, usw."""
    return int(st.session_state.get(SESSION_OFFSET_KEY, 0))


def is_history_mode() -> bool:
    return get_history_offset_days() > 0


def _set_offset(days: int) -> None:
    st.session_state[SESSION_OFFSET_KEY] = max(0, int(days))


def _window_label(offset_days: int, now: datetime | None = None) -> str:
    if offset_days <= 0:
        return "Live · Echtzeit"
    start, end, _ = history_timeline.history_window_bounds(offset_days, now)
    return (
        f"Archiv · {start.strftime('%d.%m.%Y %H:%M')} – "
        f"{end.strftime('%d.%m.%Y %H:%M')}"
    )


def render_history_navigation(now: datetime | None = None) -> int:
    """
    Zeigt ← / → und gibt den aktuellen Offset zurück.

    Zurück = älter (offset + 1); Vor = Richtung Live (offset - 1).
    """
    offset = get_history_offset_days()
    max_offset = history_timeline.max_history_offset_days(now)

    col_back, col_label, col_fwd = st.columns([1, 4, 1])
    with col_back:
        if st.button(
            "← Zurück",
            disabled=max_offset <= 0 or offset >= max_offset,
            key="history_nav_back",
            width="stretch",
        ):
            _set_offset(min(offset + 1, max_offset))
            st.rerun()
    with col_label:
        st.markdown(f"**{_window_label(offset, now)}**")
        if offset > 0 and max_offset > 0:
            st.caption(f"Schritt {offset} von {max_offset} zurück")
    with col_fwd:
        if st.button(
            "Vor →",
            disabled=offset <= 0,
            key="history_nav_forward",
            width="stretch",
        ):
            _set_offset(offset - 1)
            st.rerun()

    return get_history_offset_days()


def render_disabled_live_section(title: str) -> None:
    """Ausgegrauter Platzhalter für Live-only-Bereiche im Historie-Modus."""
    st.markdown(
        f"<div style='opacity:0.45; pointer-events:none;'>"
        f"<p><strong>{title}</strong> — nur in der Echtzeit-Ansicht verfügbar.</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
