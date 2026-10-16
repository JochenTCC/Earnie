"""Config migration registry, planner, and runner (ConfigMigration P1–P2)."""
from __future__ import annotations

from runtime_store.migration.chain import apply_chain
from runtime_store.migration.gate import (
    abort_if_migration_pending,
    abort_message_de,
    daemon_refuse_message,
    migration_blocks_normal_startup,
    plan_for_active_config,
    should_skip_offline_seed,
)
from runtime_store.migration.planner import plan_migration
from runtime_store.migration.registry import STEPS, STEP_BY_ID
from runtime_store.migration.runner import MigrationError, run_migration
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    FileDiff,
    ManualTodo,
    MigrationPlan,
    MigrationReport,
    MigrationStep,
    Question,
    StepResult,
)

__all__ = [
    "STEPS",
    "STEP_BY_ID",
    "Answers",
    "Blocker",
    "Docs",
    "FileDiff",
    "ManualTodo",
    "MigrationError",
    "MigrationPlan",
    "MigrationReport",
    "MigrationStep",
    "Question",
    "StepResult",
    "abort_if_migration_pending",
    "abort_message_de",
    "apply_chain",
    "daemon_refuse_message",
    "migration_blocks_normal_startup",
    "plan_for_active_config",
    "plan_migration",
    "run_migration",
    "should_skip_offline_seed",
]
