"""Countdown bis zum nächsten Optimierungs-Takt."""
from __future__ import annotations

import time

import streamlit as st

from optimizer import schedule as optimization_schedule
from runtime_store import run_state
from ui.runtime_config import reload_runtime_config


@st.fragment(run_every=10)
def render_countdown_block() -> None:
    """Countdown bis zur nächsten Viertelstunde (synchron zu main.py)."""
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
    app_wait = max(0, int(optimization_schedule.seconds_until_app_refresh_ready()))
    next_run = optimization_schedule.next_quarter_hour_datetime()
    last_time = time.strftime("%H:%M:%S", time.localtime(last_optimization))

    st.markdown("---")
    st.caption(
        f"🔄 **Optimierungs-Takt:** Viertelstunden (:00 / :15 / :30 / :45) | "
        f"⏱️ Letzter Lauf ({sync_label}): **{last_time}**"
    )
    st.caption(
        f"⏳ **Nächster main.py-Takt:** `{next_run.strftime('%H:%M')}` "
        f"(in `{remaining}` s) · **App-Sync** ca. 1 Min danach"
        + (f" (noch `{app_wait}` s)" if app_wait > 0 else "")
    )
