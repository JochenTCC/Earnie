"""Step dm4.loxone_binding_names — keep or clear old Loxone Merker names (2.7.q Q8).

Only offered when the chain starts at earnie_data_model 3 (``detect_on_start``):
after the run the pack is model 4 and the question never comes back, also when
the user keeps the names. Runs after the ESS move so the names travel to the
batteries first. Keys always stay as activation flags; HA / OpenEMS entity ids are
never touched.
"""
from __future__ import annotations

import copy
from typing import Any

from house_config.clear_loxone_binding_names import (
    clear_loxone_binding_names_in_components,
    clear_loxone_binding_names_in_house,
)
from runtime_store.data_model import read_data_model
from runtime_store.ehal_setup import BACKEND_LOXONE, normalize_backend
from runtime_store.migrate_v4 import LEGACY_DATA_MODEL
from runtime_store.migration.io_util import GRID_FEES_FILE
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    ManualTodo,
    MigrationStep,
    Question,
    StepResult,
)

STEP_ID = "dm4.loxone_binding_names"
Q_NAMES = "loxone_binding_names.keep"
CHOICE_KEEP = "Behalten"
CHOICE_CLEAR = "Leeren"

QUESTIONS = (
    Question(
        id=Q_NAMES,
        step_id=STEP_ID,
        prompt_de=(
            "Alte Loxone-Merkernamen in den Bindungen behalten? Earnie braucht sie "
            "nicht mehr (Signale laufen über die EHAL-ID), sie helfen aber, die "
            "Stellen in der Loxone Config zu finden (Signalliste: Spalte "
            "„Bisheriger Name“). „Leeren“ lässt die Bindungen aktiv, entfernt nur "
            "die Namen."
        ),
        kind="choice",
        required=True,
        choices=(CHOICE_KEEP, CHOICE_CLEAR),
    ),
)


def _is_loxone(docs: Docs) -> bool:
    config = docs.get("config.json")
    ehal = config.get("ehal") if isinstance(config, dict) else None
    backend = ehal.get("backend") if isinstance(ehal, dict) else None
    return normalize_backend(backend) == BACKEND_LOXONE


def _has_names(bindings: Any) -> bool:
    return isinstance(bindings, dict) and any(
        str(value or "").strip() for value in bindings.values()
    )


def _house_has_names(house: Any) -> bool:
    if not isinstance(house, dict):
        return False
    plant = house.get("plant")
    if isinstance(plant, dict) and _has_names(plant.get("ehal_bindings")):
        return True
    profiles = house.get("profiles")
    items = profiles.values() if isinstance(profiles, dict) else profiles
    if not isinstance(items, list) and not isinstance(profiles, dict):
        return False
    for profile in items:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if isinstance(consumer, dict) and _has_names(consumer.get("ehal_bindings")):
                return True
    return False


def _components_have_names(components: Any) -> bool:
    if not isinstance(components, dict):
        return False
    for section in ("batteries", "inverters", "pv_systems"):
        for entity in components.get(section) or []:
            if isinstance(entity, dict) and _has_names(entity.get("ehal_bindings")):
                return True
    return False


def detect_on_start(docs: Docs) -> bool:
    """The chain starts at model 3 (official 2.6 installs)."""
    return any(
        read_data_model(doc) == LEGACY_DATA_MODEL
        for name, doc in docs.items()
        if name != GRID_FEES_FILE
    )


def detect(docs: Docs) -> bool:
    return _is_loxone(docs) and (
        _house_has_names(docs.get("house_profiles.json"))
        or _components_have_names(docs.get("components.json"))
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    choice = answers.get(Q_NAMES)
    if choice in (None, ""):
        # Planner dry run without answers: no change; the runner requires the answer.
        return StepResult(docs=docs, changed_files=())
    if choice == CHOICE_KEEP:
        return StepResult(docs=docs, changed_files=())
    if choice != CHOICE_CLEAR:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(
                Blocker(
                    step_id=STEP_ID,
                    message_de=(
                        f"Unbekannte Antwort '{choice}' für {Q_NAMES} "
                        f"(erlaubt: {CHOICE_KEEP}, {CHOICE_CLEAR})."
                    ),
                ),
            ),
        )
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    changed: list[str] = []
    house = out.get("house_profiles.json")
    if isinstance(house, dict):
        cleared = clear_loxone_binding_names_in_house(house)
        if cleared != house:
            out["house_profiles.json"] = cleared
            changed.append("house_profiles.json")
    components = out.get("components.json")
    if isinstance(components, dict):
        cleared_c = clear_loxone_binding_names_in_components(components)
        if cleared_c != components:
            out["components.json"] = cleared_c
            changed.append("components.json")
    return StepResult(docs=out, changed_files=tuple(changed))


def manual_todos(before: Docs, after: Docs) -> list[ManualTodo]:
    del before, after
    return [
        ManualTodo(
            step_id=STEP_ID,
            text_de=(
                "Loxone Config: nach der Migration unter Echtzeit-Umgebung → EHAL-Com "
                "→ Signalliste den VI/VO-Export herunterladen und die virtuellen "
                "Ein-/Ausgänge auf die neuen Titel (EHAL-ID) umstellen. Behaltene "
                "Merkernamen stehen dort in der Spalte „Bisheriger Name“."
            ),
        )
    ]


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Loxone-Merkernamen behalten oder leeren",
    files=("house_profiles.json", "components.json"),
    detect=detect,
    apply=apply,
    questions=QUESTIONS,
    manual_todos=manual_todos,
    detect_on_start=detect_on_start,
)
