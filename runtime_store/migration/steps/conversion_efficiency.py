"""Step dm4.conversion_efficiency — split inverter/battery efficiency."""
from __future__ import annotations

import copy

from house_config.inverter import needs_conversion_efficiency_migration
from house_config.migrate_conversion_efficiency import (
    migrate_components_conversion_efficiency,
)
from runtime_store.migration.types import Answers, Docs, MigrationStep, StepResult

STEP_ID = "dm4.conversion_efficiency"


def detect(docs: Docs) -> bool:
    components = docs.get("components.json")
    return isinstance(components, dict) and needs_conversion_efficiency_migration(
        components
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    components = out.get("components.json")
    if not isinstance(components, dict):
        return StepResult(docs=out, changed_files=())
    migrated, changed = migrate_components_conversion_efficiency(components)
    if changed:
        out["components.json"] = migrated
        return StepResult(docs=out, changed_files=("components.json",))
    return StepResult(docs=out, changed_files=())


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Wirkungsgrade (η_inv / η_batt)",
    files=("components.json",),
    detect=detect,
    apply=apply,
)
