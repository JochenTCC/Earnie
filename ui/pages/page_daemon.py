"""Daemon Control: Start/Stop/Restart des main.py-Optimierer-Dienstes."""
from __future__ import annotations

import re
from datetime import timedelta
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
from runtime_store.persist_paths import log_file, resolve_local_settings_json_path
from runtime_store.shadow.mode import is_shadow_mode
from settings.system_settings import write_silent_mode_to_local_settings
from ui.help_hint import render_page_title_with_help
from ui.runtime_config import reload_runtime_config

_HELP = (
    "Startet, stoppt oder startet den Hintergrunddienst `main.py` neu. "
    "Produktions-Steuerwerte schreibt nur der laufende Dienst. "
    "Vor dem Start wird geprüft, ob bereits eine Instanz läuft (`runtime/main.lock`). "
    "Das Dienst-Log (`earnie.log`) zeigt die letzten Zeilen zum Diagnose-Blick; "
    "Log-Level sind filterbar (Standard: INFO und höher); die Anzeige aktualisiert "
    "sich alle 10 Sekunden."
)

_STATE_LABELS = {
    "running": "läuft",
    "stopped": "gestoppt",
    "unknown": "unbekannt",
}

_LOG_TAIL_LINES = 200
_LOG_TAIL_READ_BYTES = 256 * 1024
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LOG_LEVELS_DEFAULT = ["INFO", "WARNING", "ERROR", "CRITICAL"]
_LOG_LEVEL_RE = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]")
_LOG_FRAGMENT_RUN_EVERY = timedelta(seconds=10)
_LOG_ANCHOR_ID = "daemon-log-top"
_LOG_SCROLL_PENDING_KEY = "daemon_log_scroll_top"


def parse_log_level(line: str) -> str | None:
    """Return bracket log level from a line, or None if absent."""
    match = _LOG_LEVEL_RE.search(line)
    return match.group(1) if match else None


def filter_log_lines(text: str, levels: set[str]) -> str:
    """Keep lines whose ``[LEVEL]`` is in ``levels``; lines without a level stay."""
    if not text:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        level = parse_log_level(line)
        if level is None or level in levels:
            kept.append(line)
    return "\n".join(kept)


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


def _render_silent_mode_toggle() -> None:
    shadow = is_shadow_mode()
    current = bool(config.is_silent_mode())
    st.subheader("Schreibzugriffe")
    if shadow:
        st.caption(
            "Shadow-Modus (`EARNIE_SHADOW=1`): Silent-Umschalter deaktiviert — "
            "keine Sollwert-Schreibzugriffe."
        )
    else:
        st.caption(
            "Silent-Modus: keine Sollwert-Schreibzugriffe. "
            "Loud-Modus: Schreiben nur, solange der Optimierer-Dienst läuft."
        )
    silent = st.toggle(
        "Silent-Modus",
        value=current,
        disabled=shadow,
        key="daemon_silent_mode",
        help="Persistiert in runtime/local_settings.json (silent_mode).",
    )
    if shadow or silent == current:
        return
    write_silent_mode_to_local_settings(resolve_local_settings_json_path(), silent)
    reload_runtime_config()
    if silent:
        st.success("Silent-Modus aktiv — keine Schreibzugriffe.")
    else:
        st.warning(
            "Loud-Modus: Die Anlage erhält Sollwerte, sobald der Optimierer-Dienst läuft."
        )
    st.rerun()


def _scroll_to_log_top() -> None:
    """Scroll main pane to the log anchor (st.html is not iframed)."""
    st.html(
        f"""
        <script>
        (function() {{
          const el = document.getElementById('{_LOG_ANCHOR_ID}');
          if (el) {{
            el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
            return;
          }}
          const main = window.parent.document.querySelector('section.main');
          if (main) {{
            main.scrollTo({{ top: 0, behavior: 'smooth' }});
          }}
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _render_filtered_log(text: str, levels: set[str]) -> None:
    filtered = filter_log_lines(text, levels)
    total = len(text.splitlines())
    shown = len(filtered.splitlines()) if filtered else 0
    if shown < total:
        st.caption(f"Anzeige: {shown} von {total} Zeilen (Level-Filter).")
    st.code(filtered, language="log")


@st.fragment(run_every=_LOG_FRAGMENT_RUN_EVERY)
def _render_log_tail_fragment() -> None:
    st.markdown(
        f'<div id="{_LOG_ANCHOR_ID}"></div>',
        unsafe_allow_html=True,
    )
    if st.session_state.pop(_LOG_SCROLL_PENDING_KEY, False):
        _scroll_to_log_top()
    selected = st.multiselect(
        "Log-Level",
        options=list(_LOG_LEVELS),
        default=_LOG_LEVELS_DEFAULT,
        key="daemon_log_levels",
        help="Zeilen ohne [LEVEL] bleiben immer sichtbar.",
    )
    if st.button("Aktualisieren", key="daemon_log_refresh_top"):
        st.rerun()
    text, err = read_earnie_log_tail(log_file())
    if err:
        st.info(err)
    elif not text:
        st.caption("Logdatei ist leer.")
    else:
        _render_filtered_log(text, set(selected))
    col_refresh, col_top = st.columns(2)
    with col_refresh:
        if st.button("Aktualisieren", key="daemon_log_refresh_bottom", width="stretch"):
            st.rerun()
    with col_top:
        if st.button("Gehe nach Oben", key="daemon_log_go_top", width="stretch"):
            st.session_state[_LOG_SCROLL_PENDING_KEY] = True
            st.rerun()


def _render_log_section() -> None:
    st.subheader("Dienst-Log")
    path = log_file()
    with st.expander(
        f"earnie.log — letzte {_LOG_TAIL_LINES} Zeilen",
        expanded=False,
        key="daemon_log_expander",
    ):
        st.caption(f"Pfad: `{path}` · Auto-Aktualisierung alle 10 s")
        _render_log_tail_fragment()


def _warn_ehal_write_error() -> None:
    from integrations.ehal_live import load_write_error

    ehal_err = load_write_error()
    if not ehal_err:
        return
    st.warning(
        f"EHAL Schreibfehler: {ehal_err.get('message', '?')} "
        f"({', '.join(ehal_err.get('failed_fields') or [])})"
    )


def _render_lifecycle_buttons(*, running: bool, stopped: bool) -> tuple[bool, bool, bool]:
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
            disabled=stopped,
            width="stretch",
            key="daemon_stop",
        )
    with col_restart:
        do_restart = st.button(
            "Neustart",
            width="stretch",
            key="daemon_restart",
        )
    return do_start, do_stop, do_restart


def _run_lifecycle_actions(*, do_start: bool, do_stop: bool, do_restart: bool) -> None:
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


def render() -> None:
    reload_runtime_config()
    render_page_title_with_help(
        "🛠️ Optimierer-Dienst",
        _HELP,
        key="daemon_help",
        page_docs_key="optimizer-daemon",
    )
    st.caption("Lebenszyklus von `main.py` (Start / Stop / Neustart).")
    _warn_ehal_write_error()

    daemon = status()
    _render_status(daemon)
    _render_silent_mode_toggle()
    do_start, do_stop, do_restart = _render_lifecycle_buttons(
        running=daemon.state == "running",
        stopped=daemon.state == "stopped",
    )
    _run_lifecycle_actions(do_start=do_start, do_stop=do_stop, do_restart=do_restart)
    st.divider()
    _render_log_section()
