"""Step dm6.consumer_bare_bindings — one key per heat / pool read kind.

Detect-based in-model step: the signal list activated qualified keys
(``heatpump.<Kennung>.sens_temperature_heat_storage``) next to the bare keys the mapping
UI stores. The step merges each pair into the bare key (``house_config.migrate_consumer_bare_bindings``).
"""
from __future__ import annotations

import copy

from house_config.migrate_consumer_bare_bindings import (
    house_has_qualified_bare_bindings,
    migrate_house_bare_bindings,
)
from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm6.consumer_bare_bindings"


def detect(docs: Docs) -> bool:
    house = docs.get("house_profiles.json")
    return house_has_qualified_bare_bindings(house if isinstance(house, dict) else None)


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    house = out.get("house_profiles.json")
    if not isinstance(house, dict):
        return StepResult(docs=out, changed_files=())
    house_out, changed, conflicts = migrate_house_bare_bindings(house)
    if conflicts:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=tuple(Blocker(step_id=STEP_ID, message_de=msg) for msg in conflicts),
        )
    if not changed:
        return StepResult(docs=out, changed_files=())
    stamp_data_model(house_out)
    out["house_profiles.json"] = house_out
    return StepResult(docs=out, changed_files=("house_profiles.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=6,
    title_de="Wärme- und Pool-Signale nur noch unter einem Schlüssel (doppelte Aktivierung zusammenführen)",
    files=("house_profiles.json",),
    detect=detect,
    apply=apply,
)
