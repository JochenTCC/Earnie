"""Hilfetexte und leichtgewichtiger Sync-Poll app.py ↔ main.py."""
from __future__ import annotations

import streamlit as st

from optimizer import schedule as optimization_schedule
from runtime_store import run_state
from ui.fragment_refresh import MAIN_SYNC_POLL_RUN_EVERY, main_sync_poll_interval_sec

_MAX_SEC = optimization_schedule.APP_MAIN_SYNC_MAX_WAIT_SECONDS

MAIN_PY_SYNC_HELP = (
    "**main.py** führt die Produktiv-Optimierung zu Viertelstunden-Takten aus "
    "(:00 / :15 / :30 / :45).\n\n"
    "Die App aktualisiert Chart und Simulation, sobald der Lauf für den "
    "**aktuellen Slot** abgeschlossen ist (typisch wenige Sekunden). "
    "Während des Wartens prüft die App in kurzen Abständen erneut. "
    f"Spätestens nach **{_MAX_SEC} s** Fallback wird mit dem letzten Plan fortgefahren."
)


def main_py_sync_status_message(
    retry_sec: int,
    fallback_sec: int,
    reason: str,
) -> str:
    _ = reason
    fallback_hint = (
        f" (Fallback mit Altplan nach **{fallback_sec} s**)"
        if fallback_sec > 0
        else ""
    )
    return (
        f"⏳ **Warte auf main.py** für den aktuellen Viertelstunden-Slot. "
        f"Nächster Abgleich **spätestens in {retry_sec} s**{fallback_hint}."
    )


def sync_footer_caption(retry_sec: int, fallback_sec: int) -> str:
    if retry_sec <= 0 and fallback_sec <= 0:
        return " · **App-Sync** bereit"
    parts: list[str] = []
    if retry_sec > 0:
        parts.append(f"Abgleich spätestens in `{retry_sec}` s")
    if fallback_sec > 0:
        parts.append(f"Fallback nach `{fallback_sec}` s")
    return " · **App-Sync:** " + " · ".join(parts)


@st.fragment(run_every=MAIN_SYNC_POLL_RUN_EVERY)
def poll_main_py_sync_if_pending() -> None:
    """Leichtgewichtiger Abgleich mit run_state; voller Rerun bei Sync oder Fallback."""
    main_state = run_state.load_run_state()
    completed = (main_state or {}).get("completed_at")
    poll = main_sync_poll_interval_sec()
    ready, _, _, _ = optimization_schedule.live_simulation_readiness(
        completed,
        poll_sec=poll,
    )
    was_ready = st.session_state.get("main_sync_poll_ready")
    st.session_state.main_sync_poll_ready = ready
    if ready and was_ready is False:
        st.rerun()
