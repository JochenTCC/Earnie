"""Zeitnavigation für die Verbrauchs-UI (ISO-KW)."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.consumption_display.aggregation import iso_weeks_in_timestamps
from ui.consumption_validation_charts import format_iso_week_label


def render_iso_week_navigation(
    timestamps: list[str],
    *,
    key_prefix: str,
    reset_token: str | None = None,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> tuple[int, int] | None:
    """ISO-KW-Navigation (← / Label / →)."""
    weeks = iso_weeks_in_timestamps(timestamps, nav_bounds=nav_bounds)
    if not weeks:
        return None

    week_idx_key = f"{key_prefix}_week_idx"
    week_reset_key = f"{key_prefix}_week_reset"
    token = reset_token if reset_token is not None else str(len(timestamps))
    if st.session_state.get(week_reset_key) != token:
        st.session_state[week_reset_key] = token
        st.session_state[week_idx_key] = 0

    week_idx = int(st.session_state.get(week_idx_key, 0))
    week_idx = max(0, min(week_idx, len(weeks) - 1))
    st.session_state[week_idx_key] = week_idx
    iso_year, iso_week = weeks[week_idx]
    week_label = format_iso_week_label(iso_year, iso_week)

    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        gap="small",
        vertical_alignment="center",
    ):
        if st.button(
            "←",
            disabled=week_idx <= 0,
            key=f"{key_prefix}_week_back",
            help="Vorherige Kalenderwoche",
            type="secondary",
            width="content",
        ):
            st.session_state[week_idx_key] = week_idx - 1
            st.rerun()
        st.markdown(f"**{week_label}**")
        if st.button(
            "→",
            disabled=week_idx >= len(weeks) - 1,
            key=f"{key_prefix}_week_forward",
            help="Nächste Kalenderwoche",
            type="secondary",
            width="content",
        ):
            st.session_state[week_idx_key] = week_idx + 1
            st.rerun()
    return iso_year, iso_week
