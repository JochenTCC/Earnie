"""Navigation: S-2-Segmente SA₀→SA₁ / SA₁→SA₂ und Zyklen zurück im Produktiv-Log."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

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

SESSION_S2_CYCLE_OFFSET = "s2_cycle_offset"
SESSION_S2_SEGMENT_INDEX = "s2_segment_index"


def get_s2_cycle_offset() -> int:
    """0 = aktuelle SA-Anker; höher = weiter zurück im Produktiv-Log."""
    return int(st.session_state.get(SESSION_S2_CYCLE_OFFSET, 0))


def get_s2_segment_index() -> int:
    """0 = SA₀→SA₁, 1 = SA₁→SA₂."""
    return int(st.session_state.get(SESSION_S2_SEGMENT_INDEX, 0))


def is_live_s2_window() -> bool:
    """Live-Fenster SA₀→SA₁ ohne Zyklus-Offset (Auto-Refresh, Sankey-Kontext)."""
    return get_s2_cycle_offset() == 0 and get_s2_segment_index() == 0


def _set_s2_cycle_offset(cycles: int) -> None:
    st.session_state[SESSION_S2_CYCLE_OFFSET] = max(0, int(cycles))


def _set_s2_segment_index(segment: int) -> None:
    st.session_state[SESSION_S2_SEGMENT_INDEX] = 1 if int(segment) == 1 else 0


def _s2_segment_label(now: datetime | None) -> tuple[int, int, int, str]:
    """Zyklus, Segment, max_cycle und Navigations-Label für S-2."""
    cycle_offset = get_s2_cycle_offset()
    segment_index = get_s2_segment_index()
    max_cycle = max_sunrise_cycle_offset(now)
    ctx = build_live_chart_context(cycle_offset, segment_index, now=now)
    label = segment_navigation_label(
        ctx.chart_window,
        cycle_offset=cycle_offset,
        segment_index=segment_index,
    )
    return cycle_offset, segment_index, max_cycle, label


def s2_zone_help_text() -> str:
    return (
        "Hintergrund: grau = Vergangenheit · neutral = aktuelle Stunde · "
        "grün = extrapolierte Preise · "
        "«Vor →»: ein Zyklus Richtung Live oder SA₁→SA₂ (nur Live)\n\n"
        "**Soll/Ist-Icons** (nur grauer Log-Bereich): "
        "▲ Hinweis (gelb) · ◆ Warnung (orange) · ⬡ Fehler (rot). "
        "Hover zeigt Kategorie und Erläuterung. "
        "Regeln: `config/deviation_rules.json`."
    )


def render_s2_nav_buttons(now: datetime | None = None) -> None:
    """Kompakte ←/→-Navigation zwischen Chart 1 und Chart 2."""
    cycle_offset, segment_index, max_cycle, _ = _s2_segment_label(now)
    _, col_back, col_fwd, _ = st.columns([3, 1, 1, 3])
    with col_back:
        if st.button(
            "← Zurück",
            disabled=s2_back_disabled(cycle_offset, segment_index, max_cycle),
            key="s2_nav_back",
            width="stretch",
        ):
            new_cycle, new_segment = apply_s2_nav_back(
                cycle_offset, segment_index, max_cycle
            )
            _set_s2_cycle_offset(new_cycle)
            _set_s2_segment_index(new_segment)
            st.rerun()
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


def render_s2_navigation(now: datetime | None = None) -> None:
    """SA-Segment- und Zyklus-Navigation für Sunset-2-Sunset (Legacy)."""
    render_s2_nav_buttons(now=now)
