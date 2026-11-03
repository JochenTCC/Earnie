"""Step dm5.heating_power — heating-system catalog: electric nominal power → heating power.

Every ``components.json`` ``heating_systems[]`` entry with ``nominal_power_kw`` gets
``heating_power_kw`` (thermal kW) = ``nominal_power_kw`` × efficiency of its heat source
(JAZ for a heat pump, Nutzungsgrad for every other source, the stored value or the
documented default of ``share/config/heat_source_defaults.json``). The loader derives the
input power back as heating power / efficiency, so results do not change. An entry with
``nominal_power_kw`` 0 or missing gets no heating power; the loader then asks for it (fail
loud, no default). Fuel sources lose ``min_on_quarterhours`` (only the MILP of an electric
source reads it). Runs after ``dm5.heating_systems``, which moves ``nominal_power_kw`` into
the catalog in the same wizard run. Design: ``docs/dev/heating-system-variants.md``.
"""
from __future__ import annotations

import copy
from typing import Any

from house_config.heat_source import (
    heat_source_efficiency,
    heat_source_is_electric,
    normalize_heat_source,
)
from house_config.heating_systems import (
    HEATING_POWER_KEY,
    HEATING_SYSTEMS_KEY,
    LEGACY_NOMINAL_POWER_KEY,
)
from runtime_store.migration.types import Answers, Blocker, Docs, MigrationStep, StepResult

STEP_ID = "dm5.heating_power"
COMPONENTS_FILE = "components.json"
_DECIMALS = 6


def _pending_entries(components: Any) -> list[dict[str, Any]]:
    catalog = components.get(HEATING_SYSTEMS_KEY) if isinstance(components, dict) else None
    if not isinstance(catalog, list):
        return []
    return [e for e in catalog if isinstance(e, dict) and LEGACY_NOMINAL_POWER_KEY in e]


def detect(docs: Docs) -> bool:
    return bool(_pending_entries(docs.get(COMPONENTS_FILE)))


def _blocked(docs: Docs, message_de: str) -> StepResult:
    return StepResult(
        docs=docs,
        changed_files=(),
        blockers=(Blocker(step_id=STEP_ID, message_de=message_de),),
    )


def convert_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Entry with ``heating_power_kw`` in place of ``nominal_power_kw`` (key order kept).

    Raises ``ValueError`` (German) on an invalid heat source or both power fields.
    """
    label = f"Heizsystem '{entry.get('id') or '?'}'"
    if HEATING_POWER_KEY in entry:
        raise ValueError(
            f"{label}: nominal_power_kw und heating_power_kw stehen beide im Eintrag. "
            "Bitte nominal_power_kw entfernen."
        )
    heat_source = normalize_heat_source(entry.get("heat_source"), label=label)
    electric = heat_source_is_electric(heat_source)
    out: dict[str, Any] = {}
    for key, value in entry.items():
        if key == LEGACY_NOMINAL_POWER_KEY:
            nominal = float(value or 0.0)
            if nominal > 0.0:
                out[HEATING_POWER_KEY] = round(
                    nominal * heat_source_efficiency(heat_source), _DECIMALS
                )
        elif key != "min_on_quarterhours" or electric:
            out[key] = value
    return out


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    catalog = (out.get(COMPONENTS_FILE) or {}).get(HEATING_SYSTEMS_KEY) or []
    for index, entry in enumerate(catalog):
        if not isinstance(entry, dict) or LEGACY_NOMINAL_POWER_KEY not in entry:
            continue
        try:
            catalog[index] = convert_entry(entry)
        except ValueError as exc:
            return _blocked(
                docs,
                f"components.json: {exc} Bitte korrigieren und die Migration erneut starten.",
            )
    changed = (COMPONENTS_FILE,) if out.get(COMPONENTS_FILE) != docs.get(COMPONENTS_FILE) else ()
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Datenmodell 5: Heizsysteme mit Heizleistung (kW thermisch) statt Nennleistung",
    files=(COMPONENTS_FILE,),
    detect=detect,
    apply=apply,
)
