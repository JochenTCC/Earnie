"""Shared helpers for legacy migrate_* CLI wrappers → scripts.migrate_config."""
from __future__ import annotations

import sys
from pathlib import Path


def configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def run_config_migration(
    config_dir: str | Path,
    *,
    dry_run: bool = False,
    answers: dict | None = None,
) -> int:
    """Delegate to the unified migration planner/runner. Returns process exit code."""
    from runtime_store.migration import MigrationError, plan_migration, run_migration

    root = Path(config_dir)
    plan = plan_migration(root)
    if dry_run:
        print(
            f"dry-run: pending={list(plan.pending_step_ids)} "
            f"can_run={plan.can_run} blockers={len(plan.blockers)}"
        )
        for blocker in plan.blockers:
            print(f"  blocker: {blocker.message_de}")
        return 0 if (plan.can_run or not plan.pending_step_ids) else 2
    if not plan.pending_step_ids:
        print("Keine ausstehenden Migrationsschritte.")
        return 0
    try:
        report = run_migration(root, answers or {})
    except MigrationError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 1
    print(f"Backup: {report.backup_dir}")
    print("Applied:", ", ".join(report.applied_step_ids) or "(none)")
    return 0
