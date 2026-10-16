"""Guided config migration CLI (ConfigMigration P1).

Usage:
  python -m scripts.migrate_config --config-dir PATH --dry-run
  python -m scripts.migrate_config --config-dir PATH [--answers answers.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config-dir",
        required=True,
        help="Directory with Earnie pack JSON files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan and diffs without writing",
    )
    parser.add_argument(
        "--answers",
        default="",
        help="JSON object of question id → answer",
    )
    args = parser.parse_args(argv)

    from runtime_store.migration import MigrationError, plan_migration, run_migration

    config_dir = Path(args.config_dir)
    if not config_dir.is_dir():
        print(f"Abbruch: Verzeichnis fehlt: {config_dir}", file=sys.stderr)
        return 1

    answers: dict = {}
    if args.answers:
        with Path(args.answers).open(encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            print("Abbruch: --answers muss ein JSON-Objekt sein.", file=sys.stderr)
            return 1
        answers = loaded

    plan = plan_migration(config_dir)
    print(
        f"Plan: from_model={plan.from_model} → to_model={plan.to_model} "
        f"can_run={plan.can_run}"
    )
    if plan.pending_step_ids:
        print("Pending steps:")
        for step_id in plan.pending_step_ids:
            print(f"  - {step_id}")
    else:
        print("Keine ausstehenden Schritte.")
    if plan.questions:
        print("Fragen:")
        for question in plan.questions:
            req = "required" if question.required else "optional"
            print(f"  - {question.id} ({req}): {question.prompt_de}")
    if plan.blockers:
        print("Blocker:")
        for blocker in plan.blockers:
            print(f"  - [{blocker.step_id or 'plan'}] {blocker.message_de}")
    if plan.manual_todos:
        print("Manuelle Schritte:")
        for todo in plan.manual_todos:
            print(f"  - [{todo.step_id}] {todo.text_de}")
    for diff in plan.file_diffs:
        print(f"--- diff {diff.filename} ---")
        print(diff.unified_diff)

    if args.dry_run:
        return 0 if plan.can_run or not plan.pending_step_ids else 2

    if not plan.pending_step_ids:
        return 0

    try:
        report = run_migration(config_dir, answers)
    except MigrationError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 1

    print(f"Backup: {report.backup_dir}")
    print("Applied:", ", ".join(report.applied_step_ids) or "(none)")
    print("Written:", ", ".join(report.written_files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
