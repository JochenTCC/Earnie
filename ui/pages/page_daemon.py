"""Daemon Control: Start/Stop/Restart des main.py-Optimierer-Dienstes."""
from __future__ import annotations

import re
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
    "Log-Level sind filterbar (Standard: INFO und höher)."
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


def _format_cache_age(age_sec: float | None) -> str:
    if age_sec is None:
        return "—"
    if age_sec < 120:
        return f"{age_sec:.0f} s"
    if age_sec < 3600:
        return f"{age_sec / 60:.0f} min"
    return f"{age_sec / 3600:.1f} h"


def _render_price_forecast_cache_status() -> None:
    """Cross-process EU forecast disk-cache status (research path)."""
    from data.eu_forecast_disk_cache import (
        STATE_ERROR,
        STATE_INACTIVE,
        STATE_MISSING,
        STATE_READY,
        STATE_STALE,
        STATE_WARMING,
        get_eu_forecast_cache_status,
    )
    from data.price_forecast_live import (
        get_eu_power_live_source,
        get_live_bias_enabled,
        get_missing_price_strategy,
    )

    st.subheader("Preisprognose-Cache")
    try:
        source = get_eu_power_live_source()
        strategy = get_missing_price_strategy()
        bias = get_live_bias_enabled()
    except ValueError as exc:
        st.warning(f"Preisprognose-Config ungültig: {exc}")
        return

    status = get_eu_forecast_cache_status(
        eu_power_live_source=source,
        missing_price_strategy=strategy,
        live_bias_enabled=bias,
    )
    st.caption(
        f"Strategie: `{strategy}` · EU-Leistung: `{source}` · "
        f"Live-Bias: {'an' if bias else 'aus'}"
    )
    state = str(status.get("state") or STATE_MISSING)
    age = _format_cache_age(
        float(status["age_sec"]) if status.get("age_sec") is not None else None
    )
    ttl_min = float(status.get("ttl_sec") or 0) / 60.0
    rng = ""
    if status.get("range_start") and status.get("range_end"):
        rng = f" · Zeitraum `{status['range_start']}` … `{status['range_end']}`"

    if state == STATE_INACTIVE:
        st.info(
            "Research-Pfad `energy_charts_forecast` ist aus — "
            "Produkt-Stand-in (Archiv-Stundenprofil) ohne Disk-Cache-Warmup."
        )
        return
    if state == STATE_READY:
        st.success(
            f"Prognosedaten verfügbar (Alter {age}, TTL {ttl_min:.0f} min)"
            f"{rng}."
        )
        return
    if state == STATE_STALE:
        st.warning(
            f"Prognose-Cache veraltet (Alter {age}) — Hintergrund-Aktualisierung; "
            f"aktuelle Planung nutzt noch den alten Stand{rng}."
        )
        return
    if state == STATE_WARMING:
        st.info(
            "Prognosedaten werden geladen — Live nutzt vorübergehend Spiegelung "
            f"für fehlende Day-Ahead-Slots{rng}."
        )
        return
    if state == STATE_ERROR:
        err = status.get("error") or "?"
        st.warning(f"Prognose-Cache-Fehler: {err}. Fallback Spiegelung.")
        return
    st.info(
        "Prognosedaten noch nicht verfügbar — Live nutzt vorübergehend Spiegelung "
        "für fehlende Day-Ahead-Slots."
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


def _render_log_section() -> None:
    st.subheader("Dienst-Log")
    path = log_file()
    with st.expander(
        f"earnie.log — letzte {_LOG_TAIL_LINES} Zeilen",
        expanded=False,
    ):
        st.caption(f"Pfad: `{path}`")
        selected = st.multiselect(
            "Log-Level",
            options=list(_LOG_LEVELS),
            default=_LOG_LEVELS_DEFAULT,
            key="daemon_log_levels",
            help="Zeilen ohne [LEVEL] bleiben immer sichtbar.",
        )
        if st.button("Aktualisieren", key="daemon_log_refresh_top"):
            st.rerun()
        text, err = read_earnie_log_tail(path)
        if err:
            st.info(err)
            return
        if not text:
            st.caption("Logdatei ist leer.")
            return
        levels = set(selected)
        filtered = filter_log_lines(text, levels)
        total = len(text.splitlines())
        shown = len(filtered.splitlines()) if filtered else 0
        if shown < total:
            st.caption(f"Anzeige: {shown} von {total} Zeilen (Level-Filter).")
        st.code(filtered, language="log")
        if st.button("Aktualisieren", key="daemon_log_refresh_bottom"):
            st.rerun()


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
    _render_price_forecast_cache_status()
    _render_silent_mode_toggle()
    do_start, do_stop, do_restart = _render_lifecycle_buttons(
        running=daemon.state == "running",
        stopped=daemon.state == "stopped",
    )
    _run_lifecycle_actions(do_start=do_start, do_stop=do_stop, do_restart=do_restart)
    st.divider()
    _render_log_section()
