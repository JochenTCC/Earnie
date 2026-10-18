"""Step dm4.required_signal_activation — activate required EHAL keys (Binding P5a).

Detect-based in-model step: existing packs get empty ``ehal_bindings`` keys for
required signals. No silent activation on ordinary load.
"""
from __future__ import annotations

import copy

from house_config.required_signal_activation import (
    activate_required_in_components,
    activate_required_in_house,
    pack_missing_required,
)
from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.required_signal_activation"


def detect(docs: Docs) -> bool:
    house = docs.get("house_profiles.json")
    components = docs.get("components.json")
    return pack_missing_required(
        house if isinstance(house, dict) else None,
        components if isinstance(components, dict) else None,
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    changed: list[str] = []
    house = out.get("house_profiles.json")
    if isinstance(house, dict):
        updated = activate_required_in_house(house)
        stamp_data_model(updated)
        out["house_profiles.json"] = updated
        changed.append("house_profiles.json")
    components = out.get("components.json")
    if isinstance(components, dict):
        updated_c = activate_required_in_components(components)
        stamp_data_model(updated_c)
        out["components.json"] = updated_c
        changed.append("components.json")
    return StepResult(docs=out, changed_files=tuple(changed))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Pflicht-Signale in ehal_bindings aktivieren",
    files=("house_profiles.json", "components.json"),
    detect=detect,
    apply=apply,
    questions=(),
)
