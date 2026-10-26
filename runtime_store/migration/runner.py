"""Migration runner: validate → backup → atomic replace (ConfigMigration P1)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from runtime_store.data_model import CURRENT_DATA_MODEL, read_data_model
from runtime_store.migration.chain import apply_chain
from runtime_store.migration.io_util import (
    TARIFF_TRACK_FILES,
    load_pack_docs,
    replace_pack_docs,
    write_json_atomic,
)
from runtime_store.migration.planner import plan_level_blockers, plan_migration
from runtime_store.migration.registry import STEPS
from runtime_store.migration.types import (
    HANDOFF_DOCS,
    Answers,
    Docs,
    MigrationReport,
    MigrationStep,
)
from runtime_store.migration.validate import validate_migrated_docs


class MigrationError(ValueError):
    """Raised when migration cannot run or validation fails."""


def _earnie_version() -> str:
    try:
        from version import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _from_model(docs: dict[str, dict[str, Any]]) -> int | None:
    versions: list[int] = []
    for name, doc in docs.items():
        if name in TARIFF_TRACK_FILES:
            continue
        version = read_data_model(doc)
        if version is not None:
            versions.append(version)
    return min(versions) if versions else None


def _require_answers(plan_questions, answers: Answers) -> None:
    missing = [
        q.id
        for q in plan_questions
        if q.required and (q.id not in answers or answers[q.id] in (None, ""))
    ]
    if missing:
        raise MigrationError(
            "Fehlende Antworten für: " + ", ".join(missing)
        )


def migrate_docs_unattended(
    docs: Docs,
    *,
    label: str,
    steps: Iterable[MigrationStep] | None = None,
    validate_unchanged: bool = True,
) -> Docs:
    """Pure: archived pack docs through the full chain without answers (replay, pack import).

    Fails loud when a step blocks or needs an answer — an archived config is never guessed.
    Exception: dm4 questions keep their 2.7 unattended meaning (no answer = keep as is, e.g.
    Loxone Merker names); from data model 5 on a missing answer stops the run.
    Returns the migrated docs (new files such as ``user_grid_fees.json`` included).
    """
    registry = tuple(steps) if steps is not None else STEPS
    data_model_by_step = {step.id: step.data_model for step in registry}
    level = plan_level_blockers(docs)
    if level:
        raise MigrationError(f"{label}: {level[0].message_de}")
    chain = apply_chain(docs, {}, registry, stop_on_blocker=True)
    if chain.blockers:
        raise MigrationError(f"{label}: Migration blockiert: {chain.blockers[0].message_de}")
    open_questions = [
        q.id
        for q in chain.questions
        if q.required and data_model_by_step.get(q.step_id, CURRENT_DATA_MODEL) >= 5
    ]
    if open_questions:
        raise MigrationError(
            f"{label}: Migration braucht Antworten ({', '.join(open_questions)}) — "
            "archivierte Konfiguration kann nicht ohne Rückfrage migriert werden."
        )
    out = {name: doc for name, doc in chain.docs.items() if name not in HANDOFF_DOCS}
    if chain.applied_step_ids or validate_unchanged:
        validate_migrated_docs(out)
    return out


def migrate_config_dir_unattended(
    config_dir: str | Path,
    *,
    label: str,
    model_bump_only: bool = False,
) -> tuple[str, ...]:
    """Migrate a throw-away config dir in place (no backup); returns written file names.

    ``model_bump_only``: run only the steps of later data models than the docs carry
    (recorder snapshots were loadable when recorded, so same-model detect steps are skipped).
    """
    root = Path(config_dir)
    docs = load_pack_docs(root)
    steps: tuple[MigrationStep, ...] | None = None
    from_model = _from_model(docs)
    if model_bump_only and from_model is not None:
        steps = tuple(step for step in STEPS if step.data_model > from_model)
    # Nothing to migrate: the docs stay as recorded, the real loaders judge them.
    migrated = migrate_docs_unattended(
        docs, label=label, steps=steps, validate_unchanged=False
    )
    written: list[str] = []
    for name, doc in migrated.items():
        if docs.get(name) != doc:
            write_json_atomic(root / name, doc)
            written.append(name)
    return tuple(written)


def run_migration(
    config_dir: str | Path,
    answers: Answers | None = None,
    *,
    steps: Iterable[MigrationStep] | None = None,
) -> MigrationReport:
    """Apply pending migration steps and write pack files atomically."""
    root = Path(config_dir)
    answers = dict(answers or {})
    registry = tuple(steps) if steps is not None else STEPS

    plan = plan_migration(root, steps=registry)
    if not plan.can_run:
        messages = "; ".join(b.message_de for b in plan.blockers)
        raise MigrationError(f"Migration blockiert: {messages}")
    if not plan.pending_step_ids:
        return MigrationReport(
            backup_dir="",
            applied_step_ids=(),
            manual_todos=(),
            written_files=(),
        )
    _require_answers(plan.questions, answers)

    docs = load_pack_docs(root)
    level = plan_level_blockers(docs)
    if level:
        raise MigrationError(level[0].message_de)

    chain = apply_chain(docs, answers, registry, stop_on_blocker=True)
    if chain.blockers:
        raise MigrationError(chain.blockers[0].message_de)

    validate_migrated_docs(chain.docs)

    from_model = _from_model(docs)
    to_model = CURRENT_DATA_MODEL
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    from_label = "x" if from_model is None else str(from_model)
    backup_dir = (
        root
        / "backups"
        / f"pre-migration-dm{from_label}-dm{to_model}-{stamp}"
    )
    backup_dir.mkdir(parents=True, exist_ok=False)

    for name, doc in docs.items():
        write_json_atomic(backup_dir / name, doc)

    manifest = {
        "earnie_version": _earnie_version(),
        "from_model": from_model,
        "to_model": to_model,
        "step_ids": list(chain.applied_step_ids),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    write_json_atomic(backup_dir / "manifest.json", manifest)

    written = replace_pack_docs(root, chain.docs)

    report = {
        "backup_dir": str(backup_dir),
        "applied_step_ids": list(chain.applied_step_ids),
        "manual_todos": [
            {"step_id": t.step_id, "text_de": t.text_de, "export_kind": t.export_kind}
            for t in chain.manual_todos
        ],
        "written_files": list(written),
    }
    write_json_atomic(backup_dir / "report.json", report)

    return MigrationReport(
        backup_dir=str(backup_dir),
        applied_step_ids=chain.applied_step_ids,
        manual_todos=chain.manual_todos,
        written_files=written,
    )
