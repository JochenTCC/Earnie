"""Navigation: S-2-Segmente SA₀→SA₁ / SA₁→SA₂ und optional Historischer Tag (Dev)."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from runtime_store import history_timeline
from ui.chart_context import (
    build_live_chart_context,
    max_sunrise_cycle_offset,
    segment_navigation_label,
)
from ui.s2_navigation import (
    apply_s2_nav_back,
    apply_s2_nav_forward,
    s2_back_disabled,
    s2_forward_disabled,
)

SESSION_OFFSET_KEY = "history_offset_days"
SESSION_S2_CYCLE_OFFSET = "s2_cycle_offset"
SESSION_S2_SEGMENT_INDEX = "s2_segment_index"


def get_history_offset_days() -> int:
    """0 = Sunset-2-Sunset; 1+ = Historischer Tag (Dev)."""
    return int(st.session_state.get(SESSION_OFFSET_KEY, 0))


def get_s2_cycle_offset() -> int:
    """0 = aktuelle SA-Anker; höher = weiter zurück im Produktiv-Log."""
    return int(st.session_state.get(SESSION_S2_CYCLE_OFFSET, 0))


def get_s2_segment_index() -> int:
    """0 = SA₀→SA₁, 1 = SA₁→SA₂."""
    return int(st.session_state.get(SESSION_S2_SEGMENT_INDEX, 0))


def is_history_mode() -> bool:
    return get_history_offset_days() > 0


def is_live_s2_window() -> bool:
    """Live-Fenster SA₀→SA₁ ohne Zyklus-Offset (Auto-Refresh, Sankey-Kontext)."""
    return (
        not is_history_mode()
        and get_s2_cycle_offset() == 0
        and get_s2_segment_index() == 0
    )


def _set_history_offset(days: int) -> None:
    st.session_state[SESSION_OFFSET_KEY] = max(0, int(days))


def _set_s2_cycle_offset(cycles: int) -> None:
    st.session_state[SESSION_S2_CYCLE_OFFSET] = max(0, int(cycles))


def _set_s2_segment_index(segment: int) -> None:
    st.session_state[SESSION_S2_SEGMENT_INDEX] = 1 if int(segment) == 1 else 0


def _window_label(offset_days: int, now: datetime | None = None) -> str:
    if offset_days <= 0:
        return "Live · Sunset-2-Sunset"
    start, end, _ = history_timeline.history_window_bounds(offset_days, now)
    return (
        f"Archiv · {start.strftime('%d.%m.%Y %H:%M')} – "
        f"{end.strftime('%d.%m.%Y %H:%M')}"
    )


def _render_s2_navigation(now: datetime | None = None) -> None:
    cycle_offset = get_s2_cycle_offset()
    segment_index = get_s2_segment_index()
    max_cycle = max_sunrise_cycle_offset(now)
    ctx = build_live_chart_context(cycle_offset, segment_index, now=now)
    label = segment_navigation_label(
        ctx.chart_window,
        cycle_offset=cycle_offset,
        segment_index=segment_index,
    )

    col_back, col_label, col_fwd = st.columns([1, 4, 1])
    with col_back:
        back_disabled = s2_back_disabled(cycle_offset, segment_index, max_cycle)
        if st.button(
            "← Zurück",
            disabled=back_disabled,
            key="s2_nav_back",
            width="stretch",
        ):
            new_cycle, new_segment = apply_s2_nav_back(
                cycle_offset, segment_index, max_cycle
            )
            _set_s2_cycle_offset(new_cycle)
            _set_s2_segment_index(new_segment)
            st.rerun()
    with col_label:
        if cycle_offset > 0:
            st.markdown(f"**{label}** · {cycle_offset} Zyklus/Zyklen zurück")
        else:
            st.markdown(f"**{label}**")
        st.caption(
            "Hintergrund: grau = Vergangenheit · neutral = aktuelle Stunde · "
            "grün = extrapolierte Preise · "
            "«Vor →»: ein Zyklus Richtung Live oder SA₁→SA₂ (nur Live)"
        )
    with col_fwd:
        if st.button(
            "Vor →",
            disabled=s2_forward_disabled(cycle_offset, segment_index),
            key="s2_nav_forward",
            width="stretch",
        ):
            new_cycle, new_segment = apply_s2_nav_forward(
                cycle_offset, segment_index
            )
            _set_s2_cycle_offset(new_cycle)
            _set_s2_segment_index(new_segment)
            st.rerun()


def render_history_navigation(now: datetime | None = None) -> int:
    """
    Zeigt Navigation und gibt history_offset_days zurück.

    Sunset-2-Sunset: SA-Segmente und Zyklus-Navigation.
    Historischer Tag (Dev): 24h-Schritte aus dem Produktiv-Log.
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

    _render_s2_navigation(now)
    return 0


def render_disabled_live_section(title: str) -> None:
    """Ausgegrauter Platzhalter für Live-only-Bereiche im Historie-Modus."""
    st.markdown(
        f"<div style='opacity:0.45; pointer-events:none;'>"
        f"<p><strong>{title}</strong> — nur im Sunset-2-Sunset-Modus verfügbar.</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
