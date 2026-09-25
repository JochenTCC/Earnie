"""Zeitnavigation für die Verbrauchs-UI (rolling windows und ISO-KW)."""
from __future__ import annotations

import re
from datetime import date, datetime

import streamlit as st

from ui.consumption_display.period import (
    PeriodKind,
    TimeWindow,
    format_window_label,
    list_windows_for_kind,
    window_containing_date,
)
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


def parse_date_jump(text: str) -> date | None:
    """Parst TT.MM.JJJJ oder TT.MM.JJ zu einem Datum."""
    cleaned = text.strip()
    match = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$", cleaned)
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


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
    windows: list[TimeWindow],
    jump_text: str,
    *,
    period_idx_key: str,
    error_key: str,
) -> None:
    weeks = [
        (w.iso_year, w.iso_week)
        for w in windows
        if w.iso_year is not None and w.iso_week is not None
    ]
    week_idx = int(st.session_state.get(period_idx_key, 0))
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
    st.session_state[period_idx_key] = target_idx
    st.rerun()


def _apply_date_jump(
    windows: list[TimeWindow],
    jump_text: str,
    *,
    period_idx_key: str,
    error_key: str,
) -> None:
    day = parse_date_jump(jump_text)
    if day is None:
        st.session_state[error_key] = "Format: Datum, z. B. 14.09.2026."
        return
    target = window_containing_date(windows, day)
    if target is None:
        st.session_state[error_key] = (
            f"{day.strftime('%d.%m.%Y')} liegt außerhalb des Zeitraums."
        )
        return
    st.session_state.pop(error_key, None)
    st.session_state[period_idx_key] = windows.index(target)
    st.rerun()


def _render_period_chrome(
    *,
    key_prefix: str,
    period_idx: int,
    windows: list[TimeWindow],
    label: str,
    back_help: str,
    forward_help: str,
    jump_placeholder: str,
    on_jump,
) -> None:
    period_idx_key = f"{key_prefix}_period_idx"
    jump_error_key = f"{key_prefix}_period_jump_error"
    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        gap="small",
        vertical_alignment="center",
    ):
        if st.button(
            "←",
            disabled=period_idx <= 0,
            key=f"{key_prefix}_period_back",
            help=back_help,
            type="secondary",
            width="content",
        ):
            st.session_state[period_idx_key] = period_idx - 1
            st.rerun()
        st.markdown(f"**{label}**")
        if st.button(
            "→",
            disabled=period_idx >= len(windows) - 1,
            key=f"{key_prefix}_period_forward",
            help=forward_help,
            type="secondary",
            width="content",
        ):
            st.session_state[period_idx_key] = period_idx + 1
            st.rerun()

    jump_col, button_col = st.columns([3, 1])
    with jump_col:
        jump_text = st.text_input(
            "Zeitraum springen",
            placeholder=jump_placeholder,
            key=f"{key_prefix}_period_jump",
            label_visibility="collapsed",
        )
    with button_col:
        if st.button("Gehe zu", key=f"{key_prefix}_period_jump_btn", width="stretch"):
            on_jump(jump_text)

    jump_error = st.session_state.get(jump_error_key)
    if jump_error:
        st.caption(f"⚠ {jump_error}")


def _sync_period_index(
    *,
    key_prefix: str,
    windows: list[TimeWindow],
    token: str,
    default_to_latest: bool,
) -> int:
    """Reset on token change, mirror the legacy week_idx keys, clamp to range."""
    period_idx_key = f"{key_prefix}_period_idx"
    period_reset_key = f"{key_prefix}_period_reset"
    jump_error_key = f"{key_prefix}_period_jump_error"
    # Legacy ISO keys — keep reset in sync when SE/HK still use week_idx.
    legacy_week_idx_key = f"{key_prefix}_week_idx"
    legacy_week_reset_key = f"{key_prefix}_week_reset"

    if st.session_state.get(period_reset_key) != token:
        st.session_state[period_reset_key] = token
        initial = len(windows) - 1 if default_to_latest else 0
        st.session_state[period_idx_key] = initial
        st.session_state[legacy_week_reset_key] = token
        st.session_state[legacy_week_idx_key] = initial
        st.session_state.pop(jump_error_key, None)
        st.session_state.pop(f"{key_prefix}_week_jump_error", None)

    period_idx = int(st.session_state.get(period_idx_key, 0))
    period_idx = max(0, min(period_idx, len(windows) - 1))
    st.session_state[period_idx_key] = period_idx
    st.session_state[legacy_week_idx_key] = period_idx
    return period_idx


def _render_navigation_chrome(
    windows: list[TimeWindow],
    *,
    key_prefix: str,
    period_kind: PeriodKind,
    period_idx: int,
    label: str,
) -> None:
    period_idx_key = f"{key_prefix}_period_idx"
    jump_error_key = f"{key_prefix}_period_jump_error"
    is_iso_week = period_kind == PeriodKind.ISO_WEEK

    def _jump(text: str) -> None:
        apply_jump = _apply_iso_week_jump if is_iso_week else _apply_date_jump
        apply_jump(
            windows,
            text,
            period_idx_key=period_idx_key,
            error_key=jump_error_key,
        )

    _render_period_chrome(
        key_prefix=key_prefix,
        period_idx=period_idx,
        windows=windows,
        label=label,
        back_help="Vorherige Kalenderwoche" if is_iso_week else "Vorheriges Zeitfenster",
        forward_help="Nächste Kalenderwoche" if is_iso_week else "Nächstes Zeitfenster",
        jump_placeholder="12 oder 12/2025" if is_iso_week else "14.09.2026",
        on_jump=_jump,
    )


def render_period_navigation(
    timestamps: list[str],
    *,
    key_prefix: str,
    period_kind: PeriodKind,
    reset_token: str | None = None,
    nav_bounds: tuple[datetime, datetime] | None = None,
    default_to_latest: bool = False,
) -> TimeWindow | None:
    """Generic ← / label / → navigation for rolling or ISO-week windows."""
    windows = list_windows_for_kind(
        timestamps, period_kind, nav_bounds=nav_bounds
    )
    if not windows:
        return None

    token = reset_token if reset_token is not None else str(len(timestamps))
    token = f"{token}:{period_kind.value}"
    period_idx = _sync_period_index(
        key_prefix=key_prefix,
        windows=windows,
        token=token,
        default_to_latest=default_to_latest,
    )
    window = windows[period_idx]
    _render_navigation_chrome(
        windows,
        key_prefix=key_prefix,
        period_kind=period_kind,
        period_idx=period_idx,
        label=format_window_label(window),
    )
    return window


def render_iso_week_navigation(
    timestamps: list[str],
    *,
    key_prefix: str,
    reset_token: str | None = None,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> tuple[int, int] | None:
    """ISO-KW-Navigation (← / Label / →) mit Direktsprung — SE/HK wrapper."""
    window = render_period_navigation(
        timestamps,
        key_prefix=key_prefix,
        period_kind=PeriodKind.ISO_WEEK,
        reset_token=reset_token,
        nav_bounds=nav_bounds,
        default_to_latest=False,
    )
    if window is None or window.iso_year is None or window.iso_week is None:
        return None
    return window.iso_year, window.iso_week
