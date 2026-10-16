"""Step dm4.inverters — batteries[].kind → inverters[]."""
from __future__ import annotations

import copy

from house_config.inverter import needs_inverter_migration
from house_config.migrate_inverters import migrate_components_inverters
from runtime_store.migration.types import Answers, Docs, MigrationStep, StepResult

STEP_ID = "dm4.inverters"


def detect(docs: Docs) -> bool:
    components = docs.get("components.json")
    return isinstance(components, dict) and needs_inverter_migration(components)


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    components = out.get("components.json")
    if not isinstance(components, dict):
        return StepResult(docs=out, changed_files=())
    migrated, changed = migrate_components_inverters(components)
    if changed:
        out["components.json"] = migrated
        return StepResult(docs=out, changed_files=("components.json",))
    return StepResult(docs=out, changed_files=())


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Wechselrichter-Entity (inverters[])",
    files=("components.json",),
    detect=detect,
    apply=apply,
)
