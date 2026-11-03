"""Step dm5.heating_systems — inline heat generation → heating-system catalog (SUSI P1 follow-up).

Every ``thermal_annual`` consumer without ``heating_system_id`` moves ``heat_source``,
``nominal_power_kw``, ``min_on_quarterhours``, ``heat_storage`` and ``parts`` into a new
``components.json`` ``heating_systems[]`` entry ``heating_<profile_id>`` (``_2``, … on a
collision) and gets ``heating_system_id``. The entry reproduces the consumer exactly (missing
fields stay missing and keep their documented defaults), so results do not change.
Detection is content-based: packs that already ran ``dm5.heat_source`` while 2.8 was in
development migrate too. Runs after ``dm5.heat_source`` (same data model 5, one wizard run).
Design: ``docs/dev/heating-system-variants.md``.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from house_config.heating_systems import (
    HEATING_SYSTEM_ID_KEY,
    HEATING_SYSTEMS_KEY,
    reference_system_id,
)
from runtime_store.migration.types import Answers, Blocker, Docs, MigrationStep, StepResult

STEP_ID = "dm5.heating_systems"
HOUSE_FILE = "house_profiles.json"
COMPONENTS_FILE = "components.json"
# Generation fields of the inline consumer shape (frozen; ``dm5.heating_power`` then turns
# ``nominal_power_kw`` into ``heating_power_kw``).
MOVED_FIELDS: tuple[str, ...] = (
    "heat_source",
    "nominal_power_kw",
    "min_on_quarterhours",
    "heat_storage",
    "parts",
)


def _iter_profiles(house: Any) -> Iterator[dict[str, Any]]:
    profiles = house.get("profiles") if isinstance(house, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    for profile in items:
        if isinstance(profile, dict):
            yield profile


def _pending_consumers(house: Any) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for profile in _iter_profiles(house):
        for consumer in profile.get("consumers") or []:
            if (
                isinstance(consumer, dict)
                and consumer.get("type") == "thermal_annual"
                and HEATING_SYSTEM_ID_KEY not in consumer
            ):
                yield profile, consumer


def detect(docs: Docs) -> bool:
    return any(True for _ in _pending_consumers(docs.get(HOUSE_FILE)))


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    house = out.get(HOUSE_FILE)
    components = out.setdefault(COMPONENTS_FILE, {})
    catalog = components.setdefault(HEATING_SYSTEMS_KEY, [])
    if not isinstance(catalog, list):
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(
                Blocker(
                    step_id=STEP_ID,
                    message_de=(
                        "components.json: heating_systems ist kein Array. Bitte korrigieren "
                        "und die Migration erneut starten."
                    ),
                ),
            ),
        )
    taken = {str(item.get("id") or "") for item in catalog if isinstance(item, dict)}
    for profile, consumer in list(_pending_consumers(house)):
        if "heat_source" not in consumer:
            return StepResult(
                docs=docs,
                changed_files=(),
                blockers=(
                    Blocker(
                        step_id=STEP_ID,
                        message_de=(
                            f"Hausprofil '{profile.get('id')}', Verbraucher "
                            f"'{consumer.get('id')}': heat_source fehlt. Bitte in "
                            "house_profiles.json ergänzen und die Migration erneut starten."
                        ),
                    ),
                ),
            )
        profile_id = str(profile.get("id") or "").strip() or "haus"
        system_id = reference_system_id(profile_id, taken)
        taken.add(system_id)
        label = str(profile.get("label") or profile_id).strip() or profile_id
        entry: dict[str, Any] = {"id": system_id, "label": f"Heizsystem {label}"}
        for key in MOVED_FIELDS:
            if key in consumer:
                entry[key] = consumer.pop(key)
        consumer[HEATING_SYSTEM_ID_KEY] = system_id
        catalog.append(entry)
    changed = tuple(
        name
        for name in (HOUSE_FILE, COMPONENTS_FILE)
        if out.get(name) != docs.get(name)
    )
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Datenmodell 5: Wärmeerzeugung → Heizsystem-Katalog (heating_systems)",
    files=(HOUSE_FILE, COMPONENTS_FILE),
    detect=detect,
    apply=apply,
)
