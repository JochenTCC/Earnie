"""Step dm4.grid_fee_profile — legacy netznutzung scalar → object."""
from __future__ import annotations

import copy

from house_config.migrate_grid_fee import (
    migrate_document,
    needs_grid_fee_profile_migration,
)
from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    Question,
    StepResult,
)

STEP_ID = "dm4.grid_fee_profile"
Q_AREA = f"{STEP_ID}.area_id"
Q_QHM = f"{STEP_ID}.quarter_hour_meter"

QUESTIONS = (
    Question(
        id=Q_AREA,
        step_id=STEP_ID,
        prompt_de="Netzbereich-ID aus grid_fees.json (leer = eigener Basispreis)",
        kind="str",
        required=False,
    ),
    Question(
        id=Q_QHM,
        step_id=STEP_ID,
        prompt_de="Viertelstunden-Zähler vorhanden?",
        kind="bool",
        required=False,
    ),
)


def detect(docs: Docs) -> bool:
    house = docs.get("house_profiles.json")
    return isinstance(house, dict) and needs_grid_fee_profile_migration(house)


def apply(docs: Docs, answers: Answers) -> StepResult:
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    house = out.get("house_profiles.json")
    if not isinstance(house, dict):
        return StepResult(docs=out, changed_files=())

    raw_area = answers.get(Q_AREA)
    area_id: str | None
    if raw_area is None or raw_area == "":
        area_id = None
    else:
        area_id = str(raw_area).strip() or None
    qhm = bool(answers.get(Q_QHM, False))

    try:
        changed = migrate_document(
            house, area_id=area_id, quarter_hour_meter=qhm
        )
    except ValueError as exc:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(Blocker(step_id=STEP_ID, message_de=str(exc)),),
        )
    if changed:
        stamp_data_model(house)
        out["house_profiles.json"] = house
        return StepResult(docs=out, changed_files=("house_profiles.json",))
    return StepResult(docs=out, changed_files=())


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Netznutzung-Profil (Arbeitspreis → netznutzung)",
    files=("house_profiles.json",),
    detect=detect,
    apply=apply,
    questions=QUESTIONS,
)
