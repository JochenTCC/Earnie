"""Pure in-memory migration chain (ConfigMigration P1)."""
from __future__ import annotations

import copy
from typing import Iterable

from runtime_store.migration.types import (
    Answers,
    Blocker,
    ChainResult,
    Docs,
    ManualTodo,
    MigrationStep,
    Question,
    StepResult,
    step_is_pending,
    step_questions,
)


def apply_chain(
    docs: Docs,
    answers: Answers,
    steps: Iterable[MigrationStep],
    *,
    stop_on_blocker: bool = True,
) -> ChainResult:
    """Run pending steps in order. Pure — no file I/O."""
    start = copy.deepcopy(docs)
    current = copy.deepcopy(docs)
    applied: list[str] = []
    blockers: list[Blocker] = []
    todos: list[ManualTodo] = []
    questions: list[Question] = []

    for step in steps:
        if not step_is_pending(step, start, current):
            continue
        questions.extend(step_questions(step, current))
        before = copy.deepcopy(current)
        try:
            result: StepResult = step.apply(current, answers)
        except Exception as exc:  # noqa: BLE001 — map unexpected apply errors
            blockers.append(
                Blocker(step_id=step.id, message_de=str(exc) or type(exc).__name__)
            )
            if stop_on_blocker:
                break
            continue
        if result.blockers:
            blockers.extend(result.blockers)
            if stop_on_blocker:
                break
            continue
        current = result.docs
        applied.append(step.id)
        todos.extend(result.manual_todos)
        extra = step.manual_todos(before, current)
        todos.extend(extra)

    return ChainResult(
        docs=current,
        applied_step_ids=tuple(applied),
        blockers=tuple(blockers),
        manual_todos=tuple(todos),
        questions=tuple(questions),
    )
