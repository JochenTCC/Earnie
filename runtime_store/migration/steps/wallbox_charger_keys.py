"""Step dm6.wallbox_charger_keys — one key per charger kind on a wallbox.

Detect-based in-model step: after ``dm6.wallboxes`` and ``dm4.required_signal_activation`` a
migrated wallbox could hold ``set_evcs_max_current`` and ``evcs.<Wallbox>.set_evcs_max_current``.
The step merges every charger key into the qualified spelling
(``house_config.migrate_wallbox_charger_keys``); two different Merker names stop it with a
blocker for the user.
"""
from __future__ import annotations

import copy

from house_config.migrate_wallbox_charger_keys import (
    components_have_off_spelling_charger_keys,
    migrate_wallbox_charger_keys,
)
from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm6.wallbox_charger_keys"


def detect(docs: Docs) -> bool:
    components = docs.get("components.json")
    return components_have_off_spelling_charger_keys(
        components if isinstance(components, dict) else None
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    components = out.get("components.json")
    if not isinstance(components, dict):
        return StepResult(docs=out, changed_files=())
    components_out, changed, conflicts = migrate_wallbox_charger_keys(components)
    if conflicts:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=tuple(Blocker(step_id=STEP_ID, message_de=msg) for msg in conflicts),
        )
    if not changed:
        return StepResult(docs=out, changed_files=())
    stamp_data_model(components_out)
    out["components.json"] = components_out
    return StepResult(docs=out, changed_files=("components.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=6,
    title_de="Wallbox-Signale nur noch unter evcs.<Wallbox>.* (doppelte Aktivierung zusammenführen)",
    files=("components.json",),
    detect=detect,
    apply=apply,
)
