"""Navigation: Live sunrise→sunrise-Chart und Produktiv-Archiv."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from runtime_store import history_timeline
from ui.chart_context import build_live_chart_context, chart_window_label, live_now

SESSION_OFFSET_KEY = "history_offset_days"
SESSION_UI_CHART_OFFSET = "ui_chart_offset_cycles"
MAX_UI_CHART_OFFSET = 30


def get_history_offset_days() -> int:
    """0 = Live; 1 = letzter vergangener 24h-Tag, usw."""
    return int(st.session_state.get(SESSION_OFFSET_KEY, 0))


def get_ui_chart_offset() -> int:
    """0 = aktueller sunrise→sunrise-Zyklus; höher = weiter zurück."""
    return int(st.session_state.get(SESSION_UI_CHART_OFFSET, 0))


def is_history_mode() -> bool:
    return get_history_offset_days() > 0


def _set_history_offset(days: int) -> None:
    st.session_state[SESSION_OFFSET_KEY] = max(0, int(days))


def _set_ui_chart_offset(cycles: int) -> None:
    st.session_state[SESSION_UI_CHART_OFFSET] = max(0, int(cycles))


def _window_label(offset_days: int, now: datetime | None = None) -> str:
    if offset_days <= 0:
        return "Live · Echtzeit"
    start, end, _ = history_timeline.history_window_bounds(offset_days, now)
    return (
        f"Archiv · {start.strftime('%d.%m.%Y %H:%M')} – "
        f"{end.strftime('%d.%m.%Y %H:%M')}"
    )


def _render_ui_chart_navigation(now: datetime | None = None) -> None:
    moment = now if now is not None else live_now()
    ui_offset = get_ui_chart_offset()
    ctx = build_live_chart_context(ui_offset, now=moment)

    col_back, col_label, col_fwd = st.columns([1, 4, 1])
    with col_back:
        if st.button(
            "← Zurück",
            disabled=ui_offset >= MAX_UI_CHART_OFFSET,
            key="ui_chart_nav_back",
            width="stretch",
        ):
            _set_ui_chart_offset(ui_offset + 1)
            st.rerun()
    with col_label:
        label = chart_window_label(ctx.chart_window)
        if ui_offset == 0:
            st.markdown(f"**Live · {label}**")
        else:
            st.markdown(f"**{label}** · {ui_offset} Zyklus/Zyklen zurück")
        st.caption(
            "Hintergrund: grau = Vergangenheit · neutral = Live/Plan · grün = Vorausschau"
        )
    with col_fwd:
        if st.button(
            "Vor →",
            disabled=ui_offset <= 0,
            key="ui_chart_nav_forward",
            width="stretch",
        ):
            _set_ui_chart_offset(ui_offset - 1)
            st.rerun()


def render_history_navigation(now: datetime | None = None) -> int:
    """
    Zeigt Navigation und gibt history_offset_days zurück.

    Live: ←/→ verschiebt das sunrise→sunrise-Fenster.
    Archiv: ←/→ durch Produktiv-Historie (24h-Schritte).
    """
    offset = get_history_offset_days()
    if offset > 0:
        max_offset = history_timeline.max_history_offset_days(now)
        col_back, col_label, col_fwd = st.columns([1, 4, 1])
        with col_back:
            if st.button(
                "← Zurück",
                disabled=max_offset <= 0 or offset >= max_offset,
                key="history_nav_back",
                width="stretch",
            ):
                _set_history_offset(min(offset + 1, max_offset))
                st.rerun()
        with col_label:
            st.markdown(f"**{_window_label(offset, now)}**")
            if max_offset > 0:
                st.caption(f"Schritt {offset} von {max_offset} zurück")
        with col_fwd:
            if st.button(
                "Vor →",
                disabled=offset <= 0,
                key="history_nav_forward",
                width="stretch",
            ):
                _set_history_offset(offset - 1)
                st.rerun()
        return get_history_offset_days()

    _render_ui_chart_navigation(now)
    archive_col, _ = st.columns([1, 3])
    with archive_col:
        if st.button("📜 Produktiv-Archiv", key="open_prod_archive", width="stretch"):
            _set_history_offset(1)
            st.rerun()
    return 0


def render_disabled_live_section(title: str) -> None:
    """Ausgegrauter Platzhalter für Live-only-Bereiche im Historie-Modus."""
    st.markdown(
        f"<div style='opacity:0.45; pointer-events:none;'>"
        f"<p><strong>{title}</strong> — nur in der Echtzeit-Ansicht verfügbar.</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
