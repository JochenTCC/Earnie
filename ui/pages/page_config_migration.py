"""ConfigMigration P2 stub: read-only plan / blockers (full wizard = P3)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from runtime_store.migration.gate import abort_message_de, plan_for_active_config
from runtime_store.migration.types import MigrationPlan
from runtime_store.persist_paths import log_file
from version import __version__

_LOG_TAIL_LINES = 100
_LOG_TAIL_BYTES = 128 * 1024


def _last_run_version() -> str | None:
    from runtime_store.version_track import last_run_version_path

    path = last_run_version_path()
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return None
    return text or None


def _read_log_tail() -> tuple[str | None, str | None]:
    target = Path(log_file())
    if not target.is_file():
        return None, f"Logdatei nicht gefunden: `{target}`"
    try:
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > _LOG_TAIL_BYTES:
                handle.seek(size - _LOG_TAIL_BYTES)
                chunk = handle.read(_LOG_TAIL_BYTES)
                nl = chunk.find(b"\n")
                if nl >= 0:
                    chunk = chunk[nl + 1 :]
            else:
                chunk = handle.read()
        text = chunk.decode("utf-8", errors="replace")
    except OSError as exc:
        return None, f"Logdatei nicht lesbar: {exc}"
    lines = text.splitlines()
    if len(lines) > _LOG_TAIL_LINES:
        lines = lines[-_LOG_TAIL_LINES:]
    return "\n".join(lines), None


def render(plan: MigrationPlan | None = None) -> None:
    """Show pending migration / blockers and CLI pointer (no migrate button yet)."""
    resolved = plan if plan is not None else plan_for_active_config()
    st.title("Konfigurations-Migration")
    st.warning(
        f"Earnie {__version__} braucht eine Anpassung deiner Konfiguration "
        f"(Datenmodell {resolved.from_model} → {resolved.to_model}). "
        "Der volle Assistent folgt in einem späteren Update — bis dahin bitte "
        "die CLI nutzen oder Support kontaktieren."
    )
    previous = _last_run_version()
    if previous:
        st.caption(f"Zuletzt gelaufene Version: `{previous}`")

    if resolved.blockers:
        st.subheader("Blocker")
        for blocker in resolved.blockers:
            st.error(blocker.message_de)

    if resolved.pending_step_ids:
        st.subheader("Ausstehende Schritte")
        for step_id in resolved.pending_step_ids:
            st.markdown(f"- `{step_id}`")

    st.subheader("Weiter")
    st.code(
        f"python -m scripts.migrate_config --config-dir {resolved.config_dir}",
        language="bash",
    )
    st.caption(
        "Dry-Run: `--dry-run`. Nach erfolgreicher Migration Earnie neu starten."
    )
    with st.expander("Technische Zusammenfassung"):
        st.text(abort_message_de(resolved))

    st.subheader("Dienst-Log")
    text, err = _read_log_tail()
    if err:
        st.info(err)
    elif not text:
        st.caption("Logdatei ist leer.")
    else:
        st.code(text, language="log")
