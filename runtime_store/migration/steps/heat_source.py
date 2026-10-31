"""Step dm5.heat_source — flat ``heat_pump_type`` → ``heat_source`` object (SUSI P1).

Every ``thermal_annual`` consumer gets ``heat_source: {"type": "heat_pump",
"heat_pump_type": <old value>}``. A consumer without ``heat_pump_type`` was computed as an
air heat pump (``luft`` was the schema default the loader filled in), so it gets ``luft`` —
the same result, written explicitly. An old value outside ``luft`` / ``erde`` was silently
computed with the air JAZ before; the step stops with a blocker instead of guessing.
No efficiency or fuel price is written: missing values keep using the documented defaults
(``share/config/heat_source_defaults.json``). The optional ``parts[]`` (heating rod) needs
no migration. Same data model 5 as ``dm5.netznutzung_split`` (one 2.8 wizard run).
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm5.heat_source"
HOUSE_FILE = "house_profiles.json"
LEGACY_KEY = "heat_pump_type"
LEGACY_DEFAULT = "luft"
LEGACY_VALUES = ("luft", "erde")


def _iter_thermal_consumers(house: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    profiles = house.get("profiles") if isinstance(house, dict) else None
    if isinstance(profiles, dict):
        items: list[Any] = list(profiles.values())
    else:
        items = profiles if isinstance(profiles, list) else []
    for profile in items:
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id") or "?")
        for consumer in profile.get("consumers") or []:
            if isinstance(consumer, dict) and consumer.get("type") == "thermal_annual":
                yield profile_id, consumer


def _needs_migration(consumer: dict[str, Any]) -> bool:
    return LEGACY_KEY in consumer or "heat_source" not in consumer


def detect(docs: Docs) -> bool:
    return any(
        _needs_migration(consumer)
        for _pid, consumer in _iter_thermal_consumers(docs.get(HOUSE_FILE))
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    house = out.get(HOUSE_FILE)
    for profile_id, consumer in _iter_thermal_consumers(house):
        if not _needs_migration(consumer):
            continue
        raw = consumer.pop(LEGACY_KEY, None)
        hp_type = LEGACY_DEFAULT if raw in (None, "") else str(raw).strip().lower()
        if hp_type not in LEGACY_VALUES:
            return StepResult(
                docs=docs,
                changed_files=(),
                blockers=(
                    Blocker(
                        step_id=STEP_ID,
                        message_de=(
                            f"Hausprofil '{profile_id}', Verbraucher "
                            f"'{consumer.get('id')}': heat_pump_type '{raw}' ist unbekannt "
                            f"(erwartet {' / '.join(LEGACY_VALUES)}). Bitte in "
                            "house_profiles.json korrigieren und die Migration erneut starten."
                        ),
                    ),
                ),
            )
        if "heat_source" not in consumer:
            consumer["heat_source"] = {"type": "heat_pump", "heat_pump_type": hp_type}
    changed = (HOUSE_FILE,) if house != docs.get(HOUSE_FILE) else ()
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Datenmodell 5: Wärmepumpen-Typ → Wärmequelle (heat_source)",
    files=(HOUSE_FILE,),
    detect=detect,
    apply=apply,
)
