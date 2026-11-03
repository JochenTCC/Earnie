"""Step dm5.house_thermal — building fields of ``thermal_annual`` → house profile level.

The building's thermal properties belong to the house. For every profile the step writes the
switch ``heating_enabled`` („Heizung betrachten“) and ``persons`` (SUSI P6 hoist):

* with a ``thermal_annual`` consumer: ``heating_enabled: true``; the consumer's building fields
  (living area, HWB, building class, building mass, target temperature, heating limit,
  tolerance, heat-loss override, absent-mode setback) move into the profile's ``thermal`` block,
  ``persons`` to the profile. The consumer's ``absent_mode_enabled`` becomes
  ``thermal.absent_mode_enabled``. A legacy absolute ``absent_temp_c`` is turned into the
  reduction the loader computed from it before.
* without one: ``heating_enabled: false`` and ``persons`` = the schema default (the loader
  used it for nothing so far; SUSI P6 reads it).

Missing building fields stay missing: the loader fills the same documented defaults as
before, so results do not change. Two ``thermal_annual`` consumers in one profile were never
loadable and stop the step. Runs after ``dm5.heating_systems`` (same data model 5).
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from house_config.house_thermal import (
    HEATING_ENABLED_KEY,
    HOUSE_THERMAL_KEY,
    PERSONS_KEY,
)
from house_config.profile_schema_defaults import profile_default
from runtime_store.migration.types import Answers, Blocker, Docs, MigrationStep, StepResult

STEP_ID = "dm5.house_thermal"
HOUSE_FILE = "house_profiles.json"
# Consumer fields that move into the house ``thermal`` block unchanged.
_MOVED_FIELDS: tuple[str, ...] = (
    "living_area_m2",
    "hwb_kwh_m2",
    "building_class",
    "building_mass",
    "target_temp_c",
    "heating_limit_c",
    "house_tolerance_c",
    "house_heat_loss_kw_per_k",
    "absent_temp_reduction_c",
)


def _iter_profiles(house: Any) -> Iterator[dict[str, Any]]:
    profiles = house.get("profiles") if isinstance(house, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    for profile in items:
        if isinstance(profile, dict):
            yield profile


def _thermal_consumers(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        c
        for c in profile.get("consumers") or []
        if isinstance(c, dict) and c.get("type") == "thermal_annual"
    ]


def detect(docs: Docs) -> bool:
    return any(HEATING_ENABLED_KEY not in p for p in _iter_profiles(docs.get(HOUSE_FILE)))


def _blocker(message: str) -> Blocker:
    return Blocker(step_id=STEP_ID, message_de=message)


def _empty(value: Any) -> bool:
    return value is None or value == ""


# The old loader read these with ``value or default``: a stored 0 meant the default.
_FALSY_MEANS_DEFAULT = ("building_class", "building_mass", "target_temp_c", "heating_limit_c")


def _pop_field(consumer: dict[str, Any], key: str) -> Any:
    """Flat value, else the one in a nested ``thermal`` dict (as the old loader read it)."""
    value = consumer.pop(key, None)
    nested = consumer.get("thermal")
    nested_value = nested.pop(key, None) if isinstance(nested, dict) else None
    return nested_value if _empty(value) else value


def _hoist(profile: dict[str, Any], consumer: dict[str, Any]) -> None:
    """Move the building fields of ``consumer`` into ``profile`` (in place).

    Values are written so the loader computes what it computed before: falsy values the old
    loader replaced by the default are dropped, tolerance and setback keep their old clamps.
    """
    block: dict[str, Any] = dict(profile.get(HOUSE_THERMAL_KEY) or {})
    for key in _MOVED_FIELDS:
        value = _pop_field(consumer, key)
        if _empty(value) or (key in _FALSY_MEANS_DEFAULT and not value):
            continue
        if key == "house_tolerance_c":
            value = max(0.05, float(value))
        elif key == "absent_temp_reduction_c":
            value = max(0.0, float(value))
        block[key] = value
    legacy_absent = _pop_field(consumer, "absent_temp_c")
    if "absent_temp_reduction_c" not in block and not _empty(legacy_absent):
        from house_config.profile_schema_defaults import house_thermal_default

        target = block.get("target_temp_c")
        target_c = float(house_thermal_default("target_temp_c") if _empty(target) else target)
        block["absent_temp_reduction_c"] = max(0.0, target_c - float(legacy_absent))
    block["absent_mode_enabled"] = bool(consumer.pop("absent_mode_enabled", False))
    profile[HOUSE_THERMAL_KEY] = block
    persons = _pop_field(consumer, PERSONS_KEY)
    profile[PERSONS_KEY] = int(profile_default(PERSONS_KEY) if _empty(persons) else persons)
    if consumer.get("thermal") == {}:
        del consumer["thermal"]
    profile[HEATING_ENABLED_KEY] = True


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    for profile in _iter_profiles(out.get(HOUSE_FILE)):
        if HEATING_ENABLED_KEY in profile:
            continue
        consumers = _thermal_consumers(profile)
        if len(consumers) > 1:
            return StepResult(
                docs=docs,
                changed_files=(),
                blockers=(
                    _blocker(
                        f"Hausprofil '{profile.get('id')}': mehrere Verbraucher vom Typ "
                        "'thermal_annual' (Haus Wärme). Erlaubt ist einer — überzählige in "
                        "house_profiles.json entfernen und die Migration erneut starten."
                    ),
                ),
            )
        if consumers:
            _hoist(profile, consumers[0])
        else:
            profile[HEATING_ENABLED_KEY] = False
            profile.setdefault(PERSONS_KEY, int(profile_default(PERSONS_KEY)))
    changed = (HOUSE_FILE,) if out.get(HOUSE_FILE) != docs.get(HOUSE_FILE) else ()
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Datenmodell 5: Gebäude-Wärmedaten ans Hausprofil (Heizung betrachten)",
    files=(HOUSE_FILE,),
    detect=detect,
    apply=apply,
)
