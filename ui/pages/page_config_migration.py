"""ConfigMigration P3: German Streamlit wizard (plan → migrate → report → continue)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from runtime_store.migration.gate import abort_message_de, plan_for_active_config
from runtime_store.migration.registry import STEP_BY_ID
from runtime_store.migration.runner import MigrationError, run_migration
from runtime_store.migration.types import (
    Answers,
    FileDiff,
    ManualTodo,
    MigrationPlan,
    MigrationReport,
    Question,
)
from runtime_store.persist_paths import log_file
from ui.truth_banner import OFFICIAL_REPO_URL
from version import __version__

_LOG_TAIL_LINES = 100
_LOG_TAIL_BYTES = 128 * 1024
_SESSION_PHASE = "cfg_mig_phase"
_SESSION_REPORT = "cfg_mig_report"
_ANS_KEY_PREFIX = "cfg_mig_ans_"


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


def release_notes_url(version: str = __version__) -> str:
    """GitHub release page for the running Earnie version."""
    return f"{OFFICIAL_REPO_URL.rstrip('/')}/releases/tag/v{version}"


def resolve_export_bytes(export_kind: str) -> tuple[bytes, str]:
    """Return ``(data, filename)`` for a known ``export_kind``; fail loud otherwise."""
    raise ValueError(f"Unbekannter export_kind: {export_kind!r}")


def continue_after_migration() -> None:
    """Start ``main.py`` when ``EARNIE_AUTO_START_MAIN=1``; caller should ``st.rerun()``."""
    from runtime_store.main_daemon import maybe_auto_start

    maybe_auto_start()


def _store_report(report: MigrationReport) -> None:
    st.session_state[_SESSION_PHASE] = "report"
    st.session_state[_SESSION_REPORT] = {
        "backup_dir": report.backup_dir,
        "applied_step_ids": list(report.applied_step_ids),
        "written_files": list(report.written_files),
        "manual_todos": [
            {
                "step_id": t.step_id,
                "text_de": t.text_de,
                "export_kind": t.export_kind,
            }
            for t in report.manual_todos
        ],
    }


def _report_from_session() -> dict[str, Any] | None:
    raw = st.session_state.get(_SESSION_REPORT)
    return raw if isinstance(raw, dict) else None


def _clear_report_session() -> None:
    st.session_state.pop(_SESSION_PHASE, None)
    st.session_state.pop(_SESSION_REPORT, None)


def _render_hint(plan: MigrationPlan) -> None:
    from_label = "?" if plan.from_model is None else str(plan.from_model)
    st.warning(
        f"Earnie {__version__} braucht eine Anpassung deiner Konfiguration "
        f"(Datenmodell {from_label} → {plan.to_model})."
    )
    previous = _last_run_version()
    if previous:
        st.caption(f"Zuletzt gelaufene Version: `{previous}`")
    st.markdown(f"[Release Notes]({release_notes_url()})")


def _render_steps(plan: MigrationPlan) -> None:
    if not plan.pending_step_ids:
        return
    st.subheader("Schritte")
    for step_id in plan.pending_step_ids:
        step = STEP_BY_ID.get(step_id)
        if step is None:
            st.markdown(f"- `{step_id}`")
            continue
        files = ", ".join(f"`{name}`" for name in step.files) or "—"
        st.markdown(f"- **{step.title_de}** (`{step_id}`) — Dateien: {files}")
    if plan.file_diffs:
        st.subheader("Änderungen (Vorschau)")
        for diff in plan.file_diffs:
            _render_file_diff(diff)


def _render_file_diff(diff: FileDiff) -> None:
    with st.expander(diff.filename, expanded=False):
        st.code(diff.unified_diff or "(keine Diff-Ausgabe)", language="diff")


def _widget_key(question_id: str) -> str:
    return f"{_ANS_KEY_PREFIX}{question_id}"


def _render_questions(questions: tuple[Question, ...]) -> Answers:
    if not questions:
        return {}
    st.subheader("Fragen")
    answers: Answers = {}
    for question in questions:
        key = _widget_key(question.id)
        label = question.prompt_de
        if not question.required:
            label = f"{label} (optional)"
        if question.kind == "bool":
            answers[question.id] = st.checkbox(label, key=key)
        elif question.kind == "choice":
            if not question.choices:
                st.error(f"Frage `{question.id}` hat keine Auswahloptionen.")
                continue
            answers[question.id] = st.selectbox(
                label, options=list(question.choices), key=key
            )
        elif question.kind == "str":
            answers[question.id] = st.text_input(label, key=key)
        else:
            st.error(
                f"Unbekannter Fragetyp `{question.kind}` für `{question.id}`."
            )
    return answers


def _render_blockers(plan: MigrationPlan) -> None:
    if not plan.blockers:
        return
    st.subheader("Blocker")
    for blocker in plan.blockers:
        st.error(blocker.message_de)


def _render_manual_todos(
    todos: tuple[ManualTodo, ...] | list[dict[str, Any]],
    *,
    as_checklist: bool,
) -> None:
    if not todos:
        return
    st.subheader("Manuelle Schritte außerhalb von Earnie")
    for index, todo in enumerate(todos):
        if isinstance(todo, ManualTodo):
            text = todo.text_de
            export_kind = todo.export_kind
            step_id = todo.step_id
        else:
            text = str(todo.get("text_de") or "")
            export_kind = todo.get("export_kind")
            step_id = str(todo.get("step_id") or "")
        if as_checklist:
            st.checkbox(text, key=f"cfg_mig_todo_chk_{step_id}_{index}")
        else:
            st.markdown(f"- {text}")
        if export_kind:
            _render_export_download(str(export_kind), index)


def _render_export_download(export_kind: str, index: int) -> None:
    try:
        data, filename = resolve_export_bytes(export_kind)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.download_button(
        label=f"Download ({export_kind})",
        data=data,
        file_name=filename,
        key=f"cfg_mig_export_{index}_{export_kind}",
    )


def _render_migrate_button(plan: MigrationPlan, answers: Answers) -> None:
    disabled = not plan.can_run
    clicked = st.button(
        "Backup anlegen und migrieren",
        disabled=disabled,
        type="primary",
        key="cfg_mig_run",
    )
    if disabled:
        st.caption("Migration ist blockiert — siehe Blocker oben.")
        return
    if not clicked:
        return
    try:
        report = run_migration(plan.config_dir, answers)
    except MigrationError as exc:
        st.error(str(exc))
        return
    _store_report(report)
    st.rerun()


def _render_report_view() -> None:
    payload = _report_from_session()
    if payload is None:
        _clear_report_session()
        st.error("Migrationsbericht fehlt — bitte Seite neu laden.")
        return
    st.title("Konfigurations-Migration")
    st.success("Migration abgeschlossen.")
    backup = payload.get("backup_dir") or ""
    if backup:
        st.markdown(f"**Backup:** `{backup}`")
    applied = payload.get("applied_step_ids") or []
    if applied:
        st.subheader("Durchgeführte Schritte")
        for step_id in applied:
            step = STEP_BY_ID.get(str(step_id))
            title = step.title_de if step is not None else step_id
            st.markdown(f"- {title} (`{step_id}`)")
    written = payload.get("written_files") or []
    if written:
        st.caption("Geschriebene Dateien: " + ", ".join(f"`{n}`" for n in written))
    todos = payload.get("manual_todos") or []
    _render_manual_todos(todos, as_checklist=True)

    from runtime_store.env_vars import is_truthy

    if not is_truthy("AUTO_START_MAIN"):
        st.caption(
            "Auto-Start ist aus — den Optimierer danach unter "
            "**Optimierer-Dienst** starten."
        )
    if st.button("Weiter zur App", type="primary", key="cfg_mig_continue"):
        continue_after_migration()
        _clear_report_session()
        st.rerun()


def _render_log_tail() -> None:
    st.subheader("Dienst-Log")
    text, err = _read_log_tail()
    if err:
        st.info(err)
    elif not text:
        st.caption("Logdatei ist leer.")
    else:
        st.code(text, language="log")


def render(plan: MigrationPlan | None = None) -> None:
    """Guided migration wizard (German); only active in migration mode."""
    if st.session_state.get(_SESSION_PHASE) == "report":
        _render_report_view()
        return

    resolved = plan if plan is not None else plan_for_active_config()
    st.title("Konfigurations-Migration")
    _render_hint(resolved)
    _render_blockers(resolved)
    _render_steps(resolved)
    answers = _render_questions(resolved.questions)
    _render_manual_todos(resolved.manual_todos, as_checklist=False)
    _render_migrate_button(resolved, answers)

    with st.expander("CLI / technische Zusammenfassung"):
        st.code(
            f"python -m scripts.migrate_config --config-dir {resolved.config_dir}",
            language="bash",
        )
        st.caption("Dry-Run: `--dry-run`.")
        st.text(abort_message_de(resolved))

    _render_log_tail()
