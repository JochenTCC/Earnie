"""Hilfetexte und leichtgewichtiger Sync-Poll app.py ↔ main.py."""
from __future__ import annotations

import streamlit as st

from optimizer import schedule as optimization_schedule
from runtime_store import run_state
from ui.fragment_refresh import MAIN_SYNC_POLL_RUN_EVERY, main_sync_poll_interval_sec

_MAX_SEC = optimization_schedule.APP_MAIN_SYNC_MAX_WAIT_SECONDS

MAIN_PY_SYNC_HELP = (
    "**main.py** führt die Produktiv-Optimierung zu Viertelstunden-Takten aus "
    "(:00 / :15 / :30 / :45) und speichert den Anzeige-Snapshot für das Cockpit.\n\n"
    "Die App zeigt diese Daten an, sobald der Lauf für den **aktuellen Slot** "
    "abgeschlossen ist (typisch wenige Sekunden). Während des Wartens prüft die App "
    "in kurzen Abständen erneut. "
    f"Bis **{_MAX_SEC} s** wird der **letzte bekannte Plan** angezeigt — "
    "ohne eigene Live-Simulation."
)


def main_py_sync_status_message(
    retry_sec: int,
    sync_wait_sec: int,
    reason: str,
) -> str:
    _ = reason
    wait_hint = (
        f" (zeigt letzten Plan bis Sync, max. **{sync_wait_sec} s**)"
        if sync_wait_sec > 0
        else ""
    )
    return (
        f"⏳ **Warte auf main.py** für den aktuellen Viertelstunden-Slot. "
        f"Nächster Abgleich **spätestens in {retry_sec} s**{wait_hint}."
    )


def sync_footer_caption(retry_sec: int, sync_wait_sec: int) -> str:
    if retry_sec <= 0 and sync_wait_sec <= 0:
        return " · **App-Sync** bereit"
    parts: list[str] = []
    if retry_sec > 0:
        parts.append(f"Abgleich spätestens in `{retry_sec}` s")
    if sync_wait_sec > 0:
        parts.append(f"Wartefenster `{sync_wait_sec}` s")
    return " · **App-Sync:** " + " · ".join(parts)


@st.fragment(run_every=MAIN_SYNC_POLL_RUN_EVERY)
def poll_main_py_sync_if_pending() -> None:
    """Leichtgewichtiger Abgleich mit run_state; voller Rerun bei Slot-Sync."""
    main_state = run_state.load_run_state()
    completed = (main_state or {}).get("completed_at")
    poll = main_sync_poll_interval_sec()
    ready, _, _, _, _ = optimization_schedule.live_simulation_readiness(
        completed,
        poll_sec=poll,
    )
    was_ready = st.session_state.get("main_sync_poll_ready")
    st.session_state.main_sync_poll_ready = ready
    if ready and was_ready is False:
        st.rerun()
