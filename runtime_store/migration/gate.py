"""Startup gate for pending config migration (ConfigMigration P2)."""
from __future__ import annotations

import sys

from runtime_store.migration.planner import plan_migration
from runtime_store.migration.types import MigrationPlan


def plan_for_active_config() -> MigrationPlan:
    """Plan migration for the active config directory (persist_paths)."""
    from runtime_store.persist_paths import config_dir

    return plan_migration(config_dir())


def migration_blocks_normal_startup(plan: MigrationPlan) -> bool:
    """True when pending steps or blockers prevent normal load / daemon start."""
    return bool(plan.pending_step_ids) or bool(plan.blockers)


def should_skip_offline_seed(plan: MigrationPlan) -> bool:
    """
    True when bootstrap must not rewrite pack JSONs (offline demo seed).

    Skip when the Earnie track still needs a model bump (``from_model < to_model``)
    or when planner **level** blockers apply (untagged / dm1–2, ``step_id is None``).
    Detect-based dm4 step blockers alone do not skip — seed only fills empty
    live-scenario refs on ``backtesting_scenarios.json``.
    """
    if plan.from_model is not None and plan.from_model < plan.to_model:
        return True
    if any(blocker.step_id is None for blocker in plan.blockers):
        return True
    return False


def model_range_label_de(plan: MigrationPlan) -> str:
    """German label for the from/to range (avoids confusing ``4 → 4``).

    Same-model pending steps are detect-based structural work inside the
    current data model (see ``docs/spec/config-migration.md`` §3.1).
    """
    if plan.from_model is None:
        return f"Datenmodell ? → {plan.to_model}"
    if plan.from_model == plan.to_model:
        return f"strukturelle Schritte innerhalb Datenmodell {plan.to_model}"
    return f"Datenmodell {plan.from_model} → {plan.to_model}"


def abort_message_de(plan: MigrationPlan) -> str:
    """German refuse message pointing at the Streamlit migration page and CLI."""
    lines = [
        "Abbruch: Konfiguration muss zuerst migriert werden "
        f"({model_range_label_de(plan)}).",
    ]
    if plan.blockers:
        lines.append("Blocker:")
        for blocker in plan.blockers:
            lines.append(f"  - {blocker.message_de}")
    if plan.pending_step_ids:
        lines.append(
            "Ausstehende Schritte: " + ", ".join(plan.pending_step_ids)
        )
    lines.append(
        "Öffne Earnie (Streamlit) — Seite „Konfigurations-Migration“ — "
        "oder: python -m scripts.migrate_config --config-dir "
        f"{plan.config_dir}"
    )
    return "\n".join(lines)


def abort_if_migration_pending() -> MigrationPlan | None:
    """
    Refuse process start when migration is pending.

    Returns ``None`` when the config is ready. On pending/blockers: print
    German message and ``SystemExit(1)``.
    """
    plan = plan_for_active_config()
    if not migration_blocks_normal_startup(plan):
        return None
    print(abort_message_de(plan), file=sys.stderr)
    raise SystemExit(1) from None


def daemon_refuse_message(plan: MigrationPlan | None = None) -> str:
    """Message for ``DaemonError`` when migration blocks ``main_daemon.start``."""
    resolved = plan if plan is not None else plan_for_active_config()
    return abort_message_de(resolved)
