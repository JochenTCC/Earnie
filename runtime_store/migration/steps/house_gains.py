"""Step dm5.house_gains — SUSI P2: internal-gain factors and the solar-gains block, explicit.

Writes what the loader would otherwise take from the documented schema defaults, so every
pack of the 2.8 wizard run shows the new fields:

- every consumer (also a heating consumer kept with „Heizung betrachten“ off): its type's
  ``internal_gain_factor`` (generic 0.8; ev, thermal_annual, thermal_rc and the pool filter 0);
- every heating-rod part in ``components.json`` ``heating_systems``: ``internal_gain_factor`` 0;
- every profile: ``baseload_internal_gain_factor`` 0.8;
- every house ``thermal`` block: ``solar_gains`` switched **off** (opt-in, the result change is
  shown in the Hauskonfigurator) with the SUSI-cuboid window areas as a starting point.

Stored values are kept. ``gross_floor_area_m2`` is not written: missing means living area ×
1.25 (the HWB area basis, documented change). The internal gains and the H re-calibration apply
from this version on for every house with heating; release note ``## Migration``.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from house_config.house_gains import (
    BASELOAD_GAIN_FACTOR_KEY,
    INTERNAL_GAIN_FACTOR_KEY,
    SOLAR_GAINS_KEY,
    default_consumer_gain_factor,
    normalize_solar_gains,
    suggested_window_areas_m2,
)
from house_config.profile_schema_defaults import house_thermal_default, profile_default
from runtime_store.migration.types import Answers, Docs, MigrationStep, StepResult

STEP_ID = "dm5.house_gains"
HOUSE_FILE = "house_profiles.json"
COMPONENTS_FILE = "components.json"
_CONSUMER_TYPES = ("generic", "thermal_annual", "ev", "thermal_rc")


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


def _iter_parts(components: Any) -> Iterator[dict[str, Any]]:
    systems = components.get("heating_systems") if isinstance(components, dict) else None
    for system in systems or []:
        if not isinstance(system, dict):
            continue
        for part in system.get("parts") or []:
            if isinstance(part, dict):
                yield part


def _consumer_type(consumer: dict[str, Any]) -> str:
    kind = str(consumer.get("type") or "generic").strip().lower()
    return kind if kind in _CONSUMER_TYPES else "generic"


def _profile_pending(profile: dict[str, Any]) -> bool:
    if BASELOAD_GAIN_FACTOR_KEY not in profile:
        return True
    thermal = profile.get("thermal")
    if isinstance(thermal, dict) and SOLAR_GAINS_KEY not in thermal:
        return True
    return any(INTERNAL_GAIN_FACTOR_KEY not in c for c in _iter_consumers(profile))


def detect(docs: Docs) -> bool:
    if any(_profile_pending(p) for p in _iter_profiles(docs.get(HOUSE_FILE))):
        return True
    return any(INTERNAL_GAIN_FACTOR_KEY not in p for p in _iter_parts(docs.get(COMPONENTS_FILE)))


def _solar_block(thermal: dict[str, Any]) -> dict[str, Any]:
    living = thermal.get("living_area_m2")
    living_m2 = float(house_thermal_default("living_area_m2") if living in (None, "") else living)
    gross = thermal.get("gross_floor_area_m2")
    block = normalize_solar_gains({}, label="dm5.house_gains")
    block["enabled"] = False
    block["window_area_m2"] = suggested_window_areas_m2(
        living_m2, gross_floor_area_m2=float(gross) if gross not in (None, "") else None
    )
    return block


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    for profile in _iter_profiles(out.get(HOUSE_FILE)):
        profile.setdefault(BASELOAD_GAIN_FACTOR_KEY, float(profile_default(BASELOAD_GAIN_FACTOR_KEY)))
        thermal = profile.get("thermal")
        if isinstance(thermal, dict) and SOLAR_GAINS_KEY not in thermal:
            thermal[SOLAR_GAINS_KEY] = _solar_block(thermal)
        for consumer in _iter_consumers(profile):
            consumer.setdefault(
                INTERNAL_GAIN_FACTOR_KEY,
                default_consumer_gain_factor(_consumer_type(consumer), consumer.get("id")),
            )
    for part in _iter_parts(out.get(COMPONENTS_FILE)):
        part.setdefault(INTERNAL_GAIN_FACTOR_KEY, 0.0)
    changed = tuple(
        name for name in (HOUSE_FILE, COMPONENTS_FILE) if out.get(name) != docs.get(name)
    )
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de=(
        "Datenmodell 5: interne und solare Gewinne im Hausmodell (SUSI P2) — Gewinnfaktoren je "
        "Verbraucher und Grundlast, solare Gewinne vorbereitet (aus)"
    ),
    files=(HOUSE_FILE, COMPONENTS_FILE),
    detect=detect,
    apply=apply,
)
