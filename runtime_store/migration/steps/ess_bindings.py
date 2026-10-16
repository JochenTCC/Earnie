"""Step dm4.ess_bindings — plant-flat ESS + Quellenwahl onto batteries."""
from __future__ import annotations

import copy

from runtime_store.migrate_v4 import (
    MigrateV4Error,
    migrate_plant_ess_to_components,
    migrate_plant_source_select_to_standby,
    needs_ess_bindings_migration,
)
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.ess_bindings"


def detect(docs: Docs) -> bool:
    return needs_ess_bindings_migration(
        docs.get("house_profiles.json"),
        docs.get("components.json"),
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    house = out.get("house_profiles.json")
    components = out.get("components.json")
    if not isinstance(house, dict) or not isinstance(components, dict):
        return StepResult(docs=out, changed_files=())
    try:
        house_out, comp_out, changed_ess = migrate_plant_ess_to_components(
            house, components
        )
        house_out, comp_out, changed_src = migrate_plant_source_select_to_standby(
            house_out, comp_out
        )
    except MigrateV4Error as exc:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(Blocker(step_id=STEP_ID, message_de=str(exc)),),
        )
    changed_files: list[str] = []
    if changed_ess or changed_src or house_out != house:
        out["house_profiles.json"] = house_out
        changed_files.append("house_profiles.json")
    if changed_ess or changed_src or comp_out != components:
        out["components.json"] = comp_out
        changed_files.append("components.json")
    return StepResult(docs=out, changed_files=tuple(changed_files))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="ESS-Bindings (Plant-flat → Batterie / Quellenwahl)",
    files=("house_profiles.json", "components.json"),
    detect=detect,
    apply=apply,
)
