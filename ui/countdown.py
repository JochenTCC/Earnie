"""Countdown bis zum nächsten Optimierungs-Takt."""
from __future__ import annotations

import time

import streamlit as st

from optimizer import schedule as optimization_schedule
from runtime_store import run_state
from ui.fragment_refresh import STATUS_FRAGMENT_RUN_EVERY, main_sync_poll_interval_sec
from ui.help_hint import render_status_with_help
from ui.main_py_sync import MAIN_PY_SYNC_HELP, sync_footer_caption
from ui.runtime_config import reload_runtime_config
from ui.simulation_results import render_live_display_data_basis_expander


@st.fragment(run_every=STATUS_FRAGMENT_RUN_EVERY)
def _render_countdown_captions() -> None:
    """Countdown-Zeilen (Fragment-Refresh, Intervall konfigurierbar)."""
    reload_runtime_config()

    main_state = run_state.load_run_state()
    main_epoch = run_state.completed_at_epoch(main_state)
    if main_epoch is not None:
        last_optimization = main_epoch
        sync_label = "main.py"
    elif "last_optimization" in st.session_state:
        last_optimization = st.session_state.last_optimization
        sync_label = "App"
    else:
        last_optimization = time.time()
        sync_label = "App"

    remaining = max(0, int(optimization_schedule.seconds_until_next_quarter_hour()))
    poll_sec = main_sync_poll_interval_sec()
    completed = (main_state or {}).get("completed_at")
    _, _, retry_sec, sync_wait_sec, _ = optimization_schedule.live_simulation_readiness(
        completed,
        poll_sec=poll_sec,
    )
    next_run = optimization_schedule.next_quarter_hour_datetime()
    last_time = time.strftime("%H:%M:%S", time.localtime(last_optimization))

    st.caption(
        f"🔄 **Optimierungs-Takt:** Viertelstunden (:00 / :15 / :30 / :45) | "
        f"⏱️ Letzter Lauf ({sync_label}): **{last_time}**"
    )
    sync_hint = sync_footer_caption(retry_sec, sync_wait_sec)
    render_status_with_help(
        f"⏳ **Nächster main.py-Takt:** `{next_run.strftime('%H:%M')}` "
        f"(in `{remaining}` s){sync_hint}",
        MAIN_PY_SYNC_HELP,
        key="countdown_main_py_sync_help",
    )


def render_countdown_block() -> None:
    """Footer: Trennlinie, Datenbasis, Countdown bis zur nächsten Viertelstunde."""
    st.markdown("---")
    render_live_display_data_basis_expander()
    _render_countdown_captions()
