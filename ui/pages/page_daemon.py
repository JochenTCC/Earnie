"""Daemon Control: Start/Stop/Restart des main.py-Optimierer-Dienstes."""
from __future__ import annotations

import streamlit as st

from runtime_store import run_state
from runtime_store.main_daemon import (
    DaemonError,
    DaemonStatus,
    restart,
    start,
    status,
    stop,
)
from ui.help_hint import render_page_title_with_help

_HELP = (
    "Startet, stoppt oder startet den Hintergrunddienst `main.py` neu. "
    "Nur dieser Dienst schreibt Steuerwerte an Loxone. "
    "Vor dem Start wird geprüft, ob bereits eine Instanz läuft (`runtime/main.lock`)."
)

_STATE_LABELS = {
    "running": "läuft",
    "stopped": "gestoppt",
    "unknown": "unbekannt",
}


def _format_last_run() -> str:
    state = run_state.load_run_state()
    if not state:
        return "kein Laufzustand vorhanden"
    completed = state.get("completed_at")
    if not completed:
        return "kein completed_at"
    age = run_state.age_seconds(state)
    if age is None:
        return str(completed)
    if age < 120:
        return f"{completed} (vor {age:.0f} s)"
    if age < 3600:
        return f"{completed} (vor {age / 60:.0f} min)"
    return f"{completed} (vor {age / 3600:.1f} h)"


def _render_status(daemon: DaemonStatus) -> None:
    label = _STATE_LABELS.get(daemon.state, daemon.state)
    pid_text = str(daemon.pid) if daemon.pid is not None else "—"
    st.markdown(
        f"**Status:** {label}  \n"
        f"**PID:** {pid_text}  \n"
        f"**Lock:** `{daemon.lock_path}`  \n"
        f"**Letzter Optimierungslauf:** {_format_last_run()}"
    )


def render() -> None:
    render_page_title_with_help(
        "🛠️ Optimierer-Dienst",
        _HELP,
        key="daemon_help",
    )
    st.caption(
        "Lebenszyklus von `main.py` (Start / Stop / Neustart). "
        "Keine Loxone-Schreibvorgänge von dieser Seite."
    )

    daemon = status()
    _render_status(daemon)

    running = daemon.state == "running"
    col_start, col_stop, col_restart = st.columns(3)
    with col_start:
        do_start = st.button(
            "Start",
            type="primary",
            disabled=running,
            use_container_width=True,
            key="daemon_start",
        )
    with col_stop:
        do_stop = st.button(
            "Stop",
            disabled=daemon.state == "stopped",
            use_container_width=True,
            key="daemon_stop",
        )
    with col_restart:
        do_restart = st.button(
            "Neustart",
            use_container_width=True,
            key="daemon_restart",
        )

    try:
        if do_start:
            with st.spinner("Starte main.py …"):
                start()
            st.success("main.py gestartet.")
            st.rerun()
        if do_stop:
            with st.spinner("Stoppe main.py …"):
                stop()
            st.success("main.py gestoppt.")
            st.rerun()
        if do_restart:
            with st.spinner("Starte main.py neu …"):
                restart()
            st.success("main.py neu gestartet.")
            st.rerun()
    except DaemonError as exc:
        st.error(str(exc))
