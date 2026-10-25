"""Step dm4.flexible_consumers_overlay — drop the legacy ``flexible_consumers`` overlay.

Detect-based (no data-model bump). Live consumers belong to the house profile
(``house_profiles.json``); the overlay block in ``config.json`` is removed. An
empty list is dropped; a non-empty one blocks, because mapping overlay rows to
profile consumers is a manual decision (no guessing).
"""
from __future__ import annotations

import copy

from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.flexible_consumers_overlay"
_KEY = "flexible_consumers"


def detect(docs: Docs) -> bool:
    config = docs.get("config.json")
    return isinstance(config, dict) and _KEY in config


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    config = out.get("config.json")
    if not isinstance(config, dict) or _KEY not in config:
        return StepResult(docs=out, changed_files=())
    overlay = config[_KEY]
    if overlay:
        ids = ", ".join(
            str(item.get("id", "?")) if isinstance(item, dict) else "?"
            for item in (overlay if isinstance(overlay, list) else [])
        ) or "?"
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(
                Blocker(
                    step_id=STEP_ID,
                    message_de=(
                        f"config.json enthält Einträge in 'flexible_consumers' ({ids}). "
                        "Der Block ist entfernt: Verbraucher zuerst im Hausprofil "
                        "(house_profiles.json) anlegen, danach 'flexible_consumers' "
                        "aus config.json löschen."
                    ),
                ),
            ),
        )
    config.pop(_KEY)
    stamp_data_model(config)
    out["config.json"] = config
    return StepResult(docs=out, changed_files=("config.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Legacy-Block flexible_consumers entfernen",
    files=("config.json",),
    detect=detect,
    apply=apply,
)
