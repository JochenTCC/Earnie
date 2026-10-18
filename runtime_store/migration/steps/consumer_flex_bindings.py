"""Step dm4.consumer_flex_bindings — rekey flex.* → consumer|heatpump|pool.*."""
from __future__ import annotations

import copy

from house_config.migrate_consumer_flex_bindings import (
    house_has_legacy_flex_bindings,
    migrate_house_consumer_flex_bindings,
)
from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.consumer_flex_bindings"


def detect(docs: Docs) -> bool:
    house = docs.get("house_profiles.json")
    return house_has_legacy_flex_bindings(house if isinstance(house, dict) else None)


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    house = out.get("house_profiles.json")
    if not isinstance(house, dict):
        return StepResult(docs=out, changed_files=())
    house_out, changed, conflicts = migrate_house_consumer_flex_bindings(house)
    if conflicts:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=tuple(
                Blocker(step_id=STEP_ID, message_de=msg) for msg in conflicts
            ),
        )
    if not changed:
        return StepResult(docs=out, changed_files=())
    stamp_data_model(house_out)
    out["house_profiles.json"] = house_out
    return StepResult(docs=out, changed_files=("house_profiles.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Verbraucher-Bindings flex.* → consumer/heatpump/pool",
    files=("house_profiles.json",),
    detect=detect,
    apply=apply,
)
