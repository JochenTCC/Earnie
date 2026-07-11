"""Zeitnavigation für die Verbrauchs-UI (ISO-KW)."""
from __future__ import annotations

import re
from datetime import datetime

import streamlit as st

from ui.consumption_display.aggregation import iso_weeks_in_timestamps
from ui.consumption_validation_charts import format_iso_week_label


def parse_iso_week_jump(text: str) -> tuple[int, int] | None:
    """Parst '12/2025', 'KW 12/2025' oder '2025-W12' zu (iso_year, iso_week)."""
    cleaned = text.strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"^KW\s*", "", cleaned, flags=re.IGNORECASE).strip()
    iso_match = re.match(r"^(\d{4})-W(\d{1,2})$", cleaned, flags=re.IGNORECASE)
    if iso_match:
        return int(iso_match.group(1)), int(iso_match.group(2))
    if "/" not in cleaned:
        return None
    left_text, right_text = cleaned.split("/", maxsplit=1)
    if not left_text.isdigit() or not right_text.isdigit():
        return None
    left, right = int(left_text), int(right_text)
    if left > 100:
        return left, right
    return right, left


def parse_iso_week_number_only(text: str) -> int | None:
    """Parst reine Kalenderwoche (1–53), z. B. '12'."""
    cleaned = re.sub(r"^KW\s*", "", text.strip(), flags=re.IGNORECASE).strip()
    if not cleaned.isdigit():
        return None
    week = int(cleaned)
    if week < 1 or week > 53:
        return None
    return week


def resolve_iso_week_jump_target(
    jump_text: str,
    weeks: list[tuple[int, int]],
    *,
    current_idx: int = 0,
) -> tuple[int, int] | None:
    """Löst Sprungziel auf; bei reiner KW wird das ISO-Jahr aus dem Datenbereich abgeleitet."""
    parsed = parse_iso_week_jump(jump_text)
    if parsed is not None:
        return parsed
    week_only = parse_iso_week_number_only(jump_text)
    if week_only is None:
        return None
    matches = [index for index, (_, iso_week) in enumerate(weeks) if iso_week == week_only]
    if not matches:
        return None
    if len(matches) == 1:
        return weeks[matches[0]]
    best_idx = min(matches, key=lambda index: abs(index - current_idx))
    return weeks[best_idx]


def week_index_for_iso(
    weeks: list[tuple[int, int]],
    iso_year: int,
    iso_week: int,
) -> int | None:
    try:
        return weeks.index((iso_year, iso_week))
    except ValueError:
        return None


def _apply_iso_week_jump(
    weeks: list[tuple[int, int]],
    jump_text: str,
    *,
    week_idx_key: str,
    error_key: str,
) -> None:
    week_idx = int(st.session_state.get(week_idx_key, 0))
    week_only = parse_iso_week_number_only(jump_text)
    target = resolve_iso_week_jump_target(jump_text, weeks, current_idx=week_idx)
    if target is None:
        if week_only is not None:
            st.session_state[error_key] = f"KW {week_only} liegt außerhalb des Zeitraums."
        else:
            st.session_state[error_key] = "Format: KW, z. B. 12 oder 12/2025 oder 2025-W12."
        return
    iso_year, iso_week = target
    if iso_week < 1 or iso_week > 53:
        st.session_state[error_key] = f"Ungültige Kalenderwoche: {iso_week}."
        return
    target_idx = week_index_for_iso(weeks, iso_year, iso_week)
    if target_idx is None:
        st.session_state[error_key] = (
            f"{format_iso_week_label(iso_year, iso_week)} liegt außerhalb des Zeitraums."
        )
        return
    st.session_state.pop(error_key, None)
    st.session_state[week_idx_key] = target_idx
    st.rerun()


def render_iso_week_navigation(
    timestamps: list[str],
    *,
    key_prefix: str,
    reset_token: str | None = None,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> tuple[int, int] | None:
    """ISO-KW-Navigation (← / Label / →) mit Direktsprung."""
    weeks = iso_weeks_in_timestamps(timestamps, nav_bounds=nav_bounds)
    if not weeks:
        return None

    week_idx_key = f"{key_prefix}_week_idx"
    week_reset_key = f"{key_prefix}_week_reset"
    jump_error_key = f"{key_prefix}_week_jump_error"
    token = reset_token if reset_token is not None else str(len(timestamps))
    if st.session_state.get(week_reset_key) != token:
        st.session_state[week_reset_key] = token
        st.session_state[week_idx_key] = 0
        st.session_state.pop(jump_error_key, None)

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

    jump_col, button_col = st.columns([3, 1])
    with jump_col:
        jump_text = st.text_input(
            "Kalenderwoche springen",
            placeholder="12 oder 12/2025",
            key=f"{key_prefix}_week_jump",
            label_visibility="collapsed",
        )
    with button_col:
        if st.button("Gehe zu", key=f"{key_prefix}_week_jump_btn", width="stretch"):
            _apply_iso_week_jump(
                weeks,
                jump_text,
                week_idx_key=week_idx_key,
                error_key=jump_error_key,
            )

    jump_error = st.session_state.get(jump_error_key)
    if jump_error:
        st.caption(f"⚠ {jump_error}")

    return iso_year, iso_week
