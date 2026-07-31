"""Daemon Control: Start/Stop/Restart des main.py-Optimierer-Dienstes."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import config
from runtime_store import run_state
from runtime_store.main_daemon import (
    DaemonError,
    DaemonStatus,
    restart,
    start,
    status,
    stop,
)
from runtime_store.persist_paths import log_file
from ui.help_hint import render_page_title_with_help

_HELP = (
    "Startet, stoppt oder startet den Hintergrunddienst `main.py` neu. "
    "Produktions-Steuerwerte schreibt nur der laufende Dienst. "
    "Bei gestopptem Dienst können hier manuelle ESS-Test-Sollwerte "
    "an Loxone/HA/OpenEMS gesendet werden. "
    "Vor dem Start wird geprüft, ob bereits eine Instanz läuft (`runtime/main.lock`). "
    "Das Dienst-Log (`earnie.log`) zeigt die letzten Zeilen zum Diagnose-Blick."
)

_STATE_LABELS = {
    "running": "läuft",
    "stopped": "gestoppt",
    "unknown": "unbekannt",
}

_ESS_TEST_PRESETS = (
    ("Automatik", 0),
    ("Zwangsladen", 1),
    ("Entladesperre", 2),
    ("Zwangsentladen", 3),
)

_LOG_TAIL_LINES = 200
_LOG_TAIL_READ_BYTES = 256 * 1024


def read_earnie_log_tail(
    path: str | Path | None = None,
    *,
    max_lines: int = _LOG_TAIL_LINES,
    max_bytes: int = _LOG_TAIL_READ_BYTES,
) -> tuple[str | None, str | None]:
    """Return ``(tail_text, error)``. Missing/unreadable → ``(None, message)``."""
    if max_lines < 1:
        raise ValueError("max_lines must be >= 1")
    if max_bytes < 1:
        raise ValueError("max_bytes must be >= 1")
    target = Path(path) if path is not None else Path(log_file())
    if not target.is_file():
        return None, f"Logdatei nicht gefunden: `{target}`"
    try:
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                chunk = handle.read(max_bytes)
                # Drop partial first line after mid-file seek.
                nl = chunk.find(b"\n")
                if nl >= 0:
                    chunk = chunk[nl + 1 :]
            else:
                chunk = handle.read()
        text = chunk.decode("utf-8", errors="replace")
    except OSError as exc:
        return None, f"Logdatei nicht lesbar: {exc}"
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines), None


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


def _battery_max_kw() -> float:
    return float(config.get_battery_params().get("max_power_kw") or 0.0)


def _render_ess_test_section(daemon: DaemonStatus) -> None:
    from integrations.ehal_live import force_write_ess_test_setpoints

    st.subheader("ESS-Schnittstelle testen")
    st.caption(
        "Sendet Design-C1-Sollwerte (Modus + Grenzen / Sollleistung) über denselben "
        "Pfad wie `main.py`. Nur bei gestopptem Optimierer-Dienst."
    )
    max_kw = _battery_max_kw()
    input_max = max_kw if max_kw > 0 else 50.0
    default = min(1.0, input_max) if input_max > 0 else 1.0
    target_kw = st.number_input(
        "Zielleistung (kW)",
        min_value=0.0,
        max_value=float(input_max),
        value=float(default),
        step=0.1,
        key="daemon_ess_test_target_kw",
        help="Magnitude; Vorzeichen kommt aus dem Modus (Laden − / Entladen +).",
    )
    daemon_ok = daemon.state == "stopped"
    if not daemon_ok:
        st.info("Zum Testen den Optimierer-Dienst zuerst stoppen.")
    cols = st.columns(len(_ESS_TEST_PRESETS))
    clicked_mode: int | None = None
    for col, (label, mode) in zip(cols, _ESS_TEST_PRESETS):
        with col:
            if st.button(
                label,
                disabled=not daemon_ok,
                width="stretch",
                key=f"daemon_ess_test_mode_{mode}",
            ):
                clicked_mode = mode
    if clicked_mode is None:
        return
    err, records, backend = force_write_ess_test_setpoints(
        clicked_mode, float(target_kw), max_power_kw=max_kw if max_kw > 0 else None
    )
    if err:
        st.error(f"{backend}: {err}")
    else:
        st.success(f"{backend}: ESS-Test-Sollwerte gesendet (Modus {clicked_mode}).")
    if records:
        st.dataframe(records, width="stretch", hide_index=True)


def _render_log_section() -> None:
    st.subheader("Dienst-Log")
    path = log_file()
    with st.expander(
        f"earnie.log — letzte {_LOG_TAIL_LINES} Zeilen",
        expanded=False,
    ):
        st.caption(f"Pfad: `{path}`")
        if st.button("Aktualisieren", key="daemon_log_refresh"):
            st.rerun()
        text, err = read_earnie_log_tail(path)
        if err:
            st.info(err)
            return
        if not text:
            st.caption("Logdatei ist leer.")
            return
        st.code(text, language="log")


def render() -> None:
    render_page_title_with_help(
        "🛠️ Optimierer-Dienst",
        _HELP,
        key="daemon_help",
        page_docs_key="optimizer-daemon",
    )
    st.caption(
        "Lebenszyklus von `main.py` (Start / Stop / Neustart). "
        "Manuelle ESS-Test-Schreibvorgänge nur bei gestopptem Dienst."
    )

    from integrations.ehal_live import load_write_error

    ehal_err = load_write_error()
    if ehal_err:
        st.warning(
            f"EHAL Schreibfehler: {ehal_err.get('message', '?')} "
            f"({', '.join(ehal_err.get('failed_fields') or [])})"
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
            width="stretch",
            key="daemon_start",
        )
    with col_stop:
        do_stop = st.button(
            "Stop",
            disabled=daemon.state == "stopped",
            width="stretch",
            key="daemon_stop",
        )
    with col_restart:
        do_restart = st.button(
            "Neustart",
            width="stretch",
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

    st.divider()
    _render_ess_test_section(daemon)
    st.divider()
    _render_log_section()
