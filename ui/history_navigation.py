"""Navigation: S-2-Segmente SA₀→SA₁ / SA₁→SA₂ und Zyklen zurück im Produktiv-Log."""
from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from ui.chart_context import (
    build_live_chart_context,
    cycle_offset_for_sa0_date,
    max_sunrise_cycle_offset,
    sa0_date_for_s2_cycle,
    s2_date_picker_bounds,
    segment_navigation_label,
)
from ui.s2_navigation import (
    apply_s2_nav_back,
    apply_s2_nav_forward,
    apply_s2_nav_heute,
    s2_back_disabled,
    s2_forward_disabled,
    s2_heute_disabled,
)

SESSION_S2_CYCLE_OFFSET = "s2_cycle_offset"
SESSION_S2_SEGMENT_INDEX = "s2_segment_index"
SESSION_S2_DATE_PICKER = "s2_nav_date_picker"
SESSION_S2_DATE_PICKER_CYCLE = "s2_nav_date_picker_cycle"
_S2_DATE_POPOVER_KEY = "s2_nav_date_popover"
_CALENDAR_ICON = ":material/calendar_month:"


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


def _prepare_date_picker_state(display_cycle: int, sa0_date: date) -> None:
    """Picker-Wert nur vor Widget-Instanziierung setzen (Streamlit-Regel)."""
    if st.session_state.get(SESSION_S2_DATE_PICKER_CYCLE) == display_cycle:
        return
    st.session_state[SESSION_S2_DATE_PICKER] = sa0_date
    st.session_state[SESSION_S2_DATE_PICKER_CYCLE] = display_cycle


def _apply_s2_nav_state(cycle_offset: int, segment_index: int) -> None:
    _set_s2_cycle_offset(cycle_offset)
    _set_s2_segment_index(segment_index)
    st.rerun()


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
        "Navigation: «←» / «→» Zyklus, «Heute» Live-Fenster, "
        "Kalender-Icon für Datum (nur mit Log-Daten)\n\n"
        "**Soll/Ist-Icons** (nur grauer Log-Bereich): "
        "▲ Hinweis (gelb) · ◆ Warnung (orange) · ⬡ Fehler (rot). "
        "Hover zeigt Kategorie und Erläuterung. "
        "Regeln: `config/deviation_rules.json`."
    )


def _render_s2_date_picker(
    cycle_offset: int,
    segment_index: int,
    now: datetime | None,
) -> None:
    bounds = s2_date_picker_bounds(now)
    if bounds is None:
        return
    min_date, max_date = bounds
    display_cycle = 0 if segment_index == 1 else cycle_offset
    sa0_date = sa0_date_for_s2_cycle(display_cycle, now=now)
    single_date = min_date == max_date

    with st.popover(
        "",
        icon=_CALENDAR_ICON,
        type="tertiary",
        help="Datum wählen (SA₀, nur Tage mit Log-Daten)",
        key=_S2_DATE_POPOVER_KEY,
        width="content",
        disabled=single_date,
    ):
        st.caption("SA₀-Tag — aktuell in der Chart-Überschrift")
        _prepare_date_picker_state(display_cycle, sa0_date)
        picked = st.date_input(
            "S-2-Datum",
            min_value=min_date,
            max_value=max_date,
            key=SESSION_S2_DATE_PICKER,
        )
        if picked == sa0_date:
            return
        new_offset = cycle_offset_for_sa0_date(picked, now=now)
        if new_offset is None:
            st.session_state[SESSION_S2_DATE_PICKER_CYCLE] = None
            st.rerun()
            return
        if new_offset == cycle_offset and segment_index == 0:
            return
        _apply_s2_nav_state(new_offset, 0)


def render_s2_nav_buttons(now: datetime | None = None) -> None:
    """Kompakte ← / Heute / Datum / →-Navigation zwischen Chart 1 und Chart 2."""
    cycle_offset, segment_index, max_cycle, _ = _s2_segment_label(now)
    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        gap="small",
        vertical_alignment="center",
    ):
        if st.button(
            "←",
            disabled=s2_back_disabled(cycle_offset, segment_index, max_cycle),
            key="s2_nav_back",
            help="Einen Zyklus zurück",
            type="secondary",
            width="content",
        ):
            new_cycle, new_segment = apply_s2_nav_back(
                cycle_offset, segment_index, max_cycle
            )
            _apply_s2_nav_state(new_cycle, new_segment)
        if st.button(
            "Heute",
            disabled=s2_heute_disabled(cycle_offset, segment_index),
            key="s2_nav_today",
            help="Live-Fenster SA₀→SA₁",
            type="secondary",
            width="content",
        ):
            new_cycle, new_segment = apply_s2_nav_heute()
            _apply_s2_nav_state(new_cycle, new_segment)
        _render_s2_date_picker(cycle_offset, segment_index, now)
        if st.button(
            "→",
            disabled=s2_forward_disabled(cycle_offset, segment_index),
            key="s2_nav_forward",
            help="Einen Zyklus vor / Vorausschau",
            type="secondary",
            width="content",
        ):
            new_cycle, new_segment = apply_s2_nav_forward(
                cycle_offset, segment_index
            )
            _apply_s2_nav_state(new_cycle, new_segment)


def render_s2_navigation(now: datetime | None = None) -> None:
    """SA-Segment- und Zyklus-Navigation für Sunset-2-Sunset (Legacy)."""
    render_s2_nav_buttons(now=now)
