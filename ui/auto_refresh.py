"""Automatischer Seiten-Refresh beim Wechsel des Viertelstunden-Slots."""
from __future__ import annotations

import streamlit as st

import optimization_schedule


def setup_auto_refresh() -> None:
    """Seiten-Refresh beim Wechsel in den nächsten Viertelstunden-Slot."""
    current_slot = optimization_schedule.quarter_hour_slot_key()

    if "last_refresh_slot" not in st.session_state:
        st.session_state.last_refresh_slot = current_slot
        return

    if st.session_state.last_refresh_slot != current_slot:
        st.session_state.last_refresh_slot = current_slot
        st.rerun()
