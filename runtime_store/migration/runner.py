"""Migration runner: validate → backup → atomic replace (ConfigMigration P1)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from runtime_store.data_model import CURRENT_DATA_MODEL, read_data_model
from runtime_store.migration.chain import apply_chain
from runtime_store.migration.io_util import (
    GRID_FEES_FILE,
    load_pack_docs,
    replace_pack_docs,
    write_json_atomic,
)
from runtime_store.migration.planner import plan_level_blockers, plan_migration
from runtime_store.migration.registry import STEPS
from runtime_store.migration.types import (
    Answers,
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
        if name == GRID_FEES_FILE:
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
