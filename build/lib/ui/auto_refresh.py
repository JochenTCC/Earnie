"""Automatischer Seiten-Refresh beim Wechsel des Viertelstunden-Slots."""
from __future__ import annotations

import streamlit as st

from optimizer import schedule as optimization_schedule
from runtime_store import run_state


def setup_auto_refresh() -> None:
    """Seiten-Refresh bei Slot-Wechsel oder neuem main.py-Durchlauf im aktuellen Slot."""
    current_slot = optimization_schedule.quarter_hour_slot_key()
    main_state = run_state.load_run_state()
    completed = (main_state or {}).get("completed_at") or ""

    if "last_refresh_slot" not in st.session_state:
        st.session_state.last_refresh_slot = current_slot
        st.session_state.last_seen_main_completed_at = completed
        return

    slot_changed = st.session_state.last_refresh_slot != current_slot
    main_updated = (
        completed
        and completed != st.session_state.get("last_seen_main_completed_at")
        and optimization_schedule.completed_at_in_current_slot(completed)
    )

    if slot_changed:
        st.session_state.last_refresh_slot = current_slot
    if main_updated:
        st.session_state.last_seen_main_completed_at = completed

    if slot_changed or main_updated:
        st.rerun()
