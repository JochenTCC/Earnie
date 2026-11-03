"""Step dm5.house_cooling — the air conditioning moves into the house model.

Until data model 5 an air conditioner was a flag on an ordinary consumer
(``appliance_kind: "air_conditioner"`` on ``generic`` / ``thermal_rc``, for the Earnie-Points
only). It is now the ``cooling`` block of the house's heating consumer, switched with the profile
key ``cooling_enabled`` („Kühlung betrachten“, ``house_config.house_cooling``).

- every consumer: ``appliance_kind`` removed; the consumer itself stays as it was;
- every profile: ``cooling_enabled: false`` written explicitly.

The device data (capacity, SEER) cannot be derived from the old flag: each removed flag becomes a
manual to-do (enter the air conditioning under „Kühlung“ in the Hauskonfigurator).
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from house_config.consumer_points_fields import LEGACY_APPLIANCE_KIND_KEY
from house_config.house_cooling import COOLING_ENABLED_KEY
from runtime_store.migration.types import Answers, Docs, ManualTodo, MigrationStep, StepResult

STEP_ID = "dm5.house_cooling"
HOUSE_FILE = "house_profiles.json"


def _iter_profiles(house: Any) -> Iterator[dict[str, Any]]:
    profiles = house.get("profiles") if isinstance(house, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    for profile in items:
        if isinstance(profile, dict):
            yield profile


def _iter_consumers(profile: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for key in ("consumers", "inactive_consumers"):
        for consumer in profile.get(key) or []:
            if isinstance(consumer, dict):
                yield consumer


def _profile_pending(profile: dict[str, Any]) -> bool:
    if COOLING_ENABLED_KEY not in profile:
        return True
    return any(LEGACY_APPLIANCE_KIND_KEY in c for c in _iter_consumers(profile))


def detect(docs: Docs) -> bool:
    return any(_profile_pending(p) for p in _iter_profiles(docs.get(HOUSE_FILE)))


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    todos: list[ManualTodo] = []
    for profile in _iter_profiles(out.get(HOUSE_FILE)):
        profile.setdefault(COOLING_ENABLED_KEY, False)
        for consumer in _iter_consumers(profile):
            if LEGACY_APPLIANCE_KIND_KEY not in consumer:
                continue
            kind = consumer.pop(LEGACY_APPLIANCE_KIND_KEY)
            if kind == "air_conditioner":
                label = consumer.get("label") or consumer.get("id") or "?"
                todos.append(
                    ManualTodo(
                        step_id=STEP_ID,
                        text_de=(
                            f"Hausprofil '{profile.get('id')}': Verbraucher '{label}' war als "
                            "Klimaanlage markiert. Die Klimaanlage im Hauskonfigurator unter "
                            "„Kühlung“ eintragen (Gerät, Kälteleistung, SEER) und „Kühlung "
                            "betrachten“ einschalten; den Verbraucher danach entfernen, sonst "
                            "zählt sein Strom doppelt."
                        ),
                    )
                )
    changed = (HOUSE_FILE,) if out.get(HOUSE_FILE) != docs.get(HOUSE_FILE) else ()
    return StepResult(docs=out, changed_files=changed, manual_todos=tuple(todos))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de=(
        "Datenmodell 5: Klimaanlage im Hausmodell — Geräteart „Klimaanlage“ an Verbrauchern "
        "entfernt, Schalter „Kühlung betrachten“ (aus)"
    ),
    files=(HOUSE_FILE,),
    detect=detect,
    apply=apply,
)
