"""Shared types for the config migration registry (ConfigMigration P1)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

Docs = dict[str, dict[str, Any]]
Answers = dict[str, Any]


@dataclass(frozen=True)
class Question:
    id: str
    step_id: str
    prompt_de: str
    kind: str  # "str" | "bool" | "choice"
    required: bool
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualTodo:
    step_id: str
    text_de: str
    export_kind: str | None = None


@dataclass(frozen=True)
class Blocker:
    step_id: str | None
    message_de: str


@dataclass(frozen=True)
class StepResult:
    docs: Docs
    changed_files: tuple[str, ...]
    blockers: tuple[Blocker, ...] = ()
    manual_todos: tuple[ManualTodo, ...] = ()


@dataclass(frozen=True)
class FileDiff:
    filename: str
    unified_diff: str


@dataclass(frozen=True)
class MigrationPlan:
    config_dir: str
    from_model: int | None
    to_model: int
    pending_step_ids: tuple[str, ...]
    questions: tuple[Question, ...]
    blockers: tuple[Blocker, ...]
    manual_todos: tuple[ManualTodo, ...]
    file_diffs: tuple[FileDiff, ...]
    can_run: bool


@dataclass(frozen=True)
class MigrationReport:
    backup_dir: str
    applied_step_ids: tuple[str, ...]
    manual_todos: tuple[ManualTodo, ...]
    written_files: tuple[str, ...]


@dataclass(frozen=True)
class ChainResult:
    docs: Docs
    applied_step_ids: tuple[str, ...]
    blockers: tuple[Blocker, ...]
    manual_todos: tuple[ManualTodo, ...]
    questions: tuple[Question, ...]


def _empty_manual_todos(_before: Docs, _after: Docs) -> list[ManualTodo]:
    return []


@dataclass(frozen=True)
class MigrationStep:
    id: str
    data_model: int
    title_de: str
    files: tuple[str, ...]
    detect: Callable[[Docs], bool]
    apply: Callable[[Docs, Answers], StepResult]
    questions: tuple[Question, ...] = ()
    manual_todos: Callable[[Docs, Docs], list[ManualTodo]] = _empty_manual_todos
    # Optional gate on the docs the chain started from (e.g. "only from model 3").
    detect_on_start: Callable[[Docs], bool] | None = None


def step_is_pending(step: MigrationStep, start: Docs, current: Docs) -> bool:
    """``detect_on_start`` (on the chain's input) and ``detect`` (on current docs)."""
    if step.detect_on_start is not None and not step.detect_on_start(start):
        return False
    return step.detect(current)
