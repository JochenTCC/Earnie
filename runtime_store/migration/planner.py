"""Read-only migration planner (ConfigMigration P1)."""
from __future__ import annotations

import copy
import difflib
from pathlib import Path
from typing import Iterable

from runtime_store.data_model import CURRENT_DATA_MODEL, read_data_model
from runtime_store.migration.chain import apply_chain
from runtime_store.migration.io_util import (
    EARNIE_TRACK_FILES,
    GRID_FEES_FILE,
    load_pack_docs,
    stable_json_text,
)
from runtime_store.migration.registry import STEPS
from runtime_store.migration.types import (
    Blocker,
    Docs,
    FileDiff,
    MigrationPlan,
    MigrationStep,
    Question,
    step_is_pending,
)


def _min_model(docs: Docs) -> int | None:
    versions: list[int] = []
    for name, doc in docs.items():
        if name == GRID_FEES_FILE:
            continue
        version = read_data_model(doc)
        if version is not None:
            versions.append(version)
    if not versions:
        return None
    return min(versions)


def plan_level_blockers(docs: Docs) -> list[Blocker]:
    """dm1/2 and untagged Earnie-track files (grid_fees exempt in 2.7)."""
    blockers: list[Blocker] = []
    for name, doc in docs.items():
        if name not in EARNIE_TRACK_FILES:
            continue
        version = read_data_model(doc)
        if version is None:
            blockers.append(
                Blocker(
                    step_id=None,
                    message_de=(
                        f"{name}: earnie_data_model fehlt (Version unbekannt) — "
                        "bitte Support kontaktieren oder Datei mit bekannter Version "
                        "wiederherstellen."
                    ),
                )
            )
            continue
        if version in (1, 2):
            blockers.append(
                Blocker(
                    step_id=None,
                    message_de=(
                        f"{name}: Konfiguration zu alt (earnie_data_model={version}) — "
                        "bitte Support kontaktieren / neu einrichten."
                    ),
                )
            )
    return blockers


def _file_diffs(before: Docs, after: Docs) -> tuple[FileDiff, ...]:
    names = sorted(set(before) | set(after))
    diffs: list[FileDiff] = []
    for name in names:
        old = before.get(name)
        new = after.get(name)
        if old == new:
            continue
        old_text = stable_json_text(old) if isinstance(old, dict) else ""
        new_text = stable_json_text(new) if isinstance(new, dict) else ""
        unified = "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
        diffs.append(FileDiff(filename=name, unified_diff=unified))
    return tuple(diffs)


def _pending_and_questions(
    docs: Docs, registry: tuple[MigrationStep, ...]
) -> tuple[tuple[str, ...], tuple[Question, ...]]:
    """List steps that detect true along a dry-run chain (stops at first blocker)."""
    start = copy.deepcopy(docs)
    current = copy.deepcopy(docs)
    pending: list[str] = []
    questions: list[Question] = []
    for step in registry:
        if not step_is_pending(step, start, current):
            continue
        pending.append(step.id)
        questions.extend(step.questions)
        result = step.apply(current, {})
        if result.blockers:
            break
        current = result.docs
    return tuple(pending), tuple(questions)


def plan_migration(
    config_dir: str | Path,
    *,
    steps: Iterable[MigrationStep] | None = None,
) -> MigrationPlan:
    """Build a dry-run migration plan for ``config_dir``."""
    root = str(Path(config_dir))
    docs = load_pack_docs(root)
    registry = tuple(steps) if steps is not None else STEPS
    blockers = plan_level_blockers(docs)
    from_model = _min_model(docs)

    if blockers:
        return MigrationPlan(
            config_dir=root,
            from_model=from_model,
            to_model=CURRENT_DATA_MODEL,
            pending_step_ids=(),
            questions=(),
            blockers=tuple(blockers),
            manual_todos=(),
            file_diffs=(),
            can_run=False,
        )

    pending, questions = _pending_and_questions(docs, registry)
    chain = apply_chain(docs, {}, registry, stop_on_blocker=True)
    all_blockers = tuple(chain.blockers)
    file_diffs = _file_diffs(docs, chain.docs) if pending else ()

    return MigrationPlan(
        config_dir=root,
        from_model=from_model,
        to_model=CURRENT_DATA_MODEL,
        pending_step_ids=pending,
        questions=questions,
        blockers=all_blockers,
        manual_todos=tuple(chain.manual_todos),
        file_diffs=file_diffs,
        can_run=not all_blockers,
    )
