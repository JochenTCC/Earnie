"""Step dm4.v3_to_v4 — earnie_data_model 3 → 4 pack migrate."""
from __future__ import annotations

import copy

from runtime_store.migrate_v4 import MigrateV4Error, migrate_pack_docs, needs_v4_migration
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.v3_to_v4"


def detect(docs: Docs) -> bool:
    return any(needs_v4_migration(doc) for doc in docs.values())


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    # Do not stamp grid_fees.json onto earnie_data_model (tariff track / 2.7 exempt).
    work = {
        name: copy.deepcopy(doc)
        for name, doc in docs.items()
        if name != "grid_fees.json"
    }
    held_grid = docs.get("grid_fees.json")
    try:
        out = migrate_pack_docs(work)
    except MigrateV4Error as exc:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(Blocker(step_id=STEP_ID, message_de=str(exc)),),
        )
    if isinstance(held_grid, dict):
        out["grid_fees.json"] = copy.deepcopy(held_grid)
    changed = tuple(
        name for name in out if name != "grid_fees.json" and docs.get(name) != out.get(name)
    )
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Datenmodell 3 → 4 (Multi-ESS / Szenarien)",
    files=(
        "config.json",
        "backtesting_scenarios.json",
        "components.json",
        "deviation_rules.json",
        "house_profiles.json",
        "tariffs.json",
        "grid_fees.json",
    ),
    detect=detect,
    apply=apply,
)
