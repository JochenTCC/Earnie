"""Step dm4.v3_to_v4 — earnie_data_model 3 → 4 pack migrate."""
from __future__ import annotations

import copy

from runtime_store.data_model import TARIFF_TRACK_FILES
from runtime_store.migrate_v4 import MigrateV4Error, migrate_pack_docs, needs_v4_migration
from runtime_store.migration.steps.inverters import pv_on_main_inverter_todos
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    ManualTodo,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.v3_to_v4"


def detect(docs: Docs) -> bool:
    return any(needs_v4_migration(doc) for doc in docs.values())


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    # Do not stamp tariff-track files onto earnie_data_model (grid_fees, user_tariffs).
    work = {
        name: copy.deepcopy(doc)
        for name, doc in docs.items()
        if name not in TARIFF_TRACK_FILES
    }
    held = {name: docs[name] for name in TARIFF_TRACK_FILES if name in docs}
    try:
        out = migrate_pack_docs(work)
    except MigrateV4Error as exc:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(Blocker(step_id=STEP_ID, message_de=str(exc)),),
        )
    for name, doc in held.items():
        if isinstance(doc, dict):
            out[name] = copy.deepcopy(doc)
    changed = tuple(
        name
        for name in out
        if name not in TARIFF_TRACK_FILES and docs.get(name) != out.get(name)
    )
    return StepResult(docs=out, changed_files=changed)


def manual_todos(before: Docs, after: Docs) -> list[ManualTodo]:
    return pv_on_main_inverter_todos(before, after, STEP_ID)


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
    manual_todos=manual_todos,
)
