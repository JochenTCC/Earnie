"""Step dm4.topology — regulates_on + plant.grid_meter seeds."""
from __future__ import annotations

import copy

from house_config.migrate_topology import (
    migrate_components_topology,
    migrate_house_profiles_grid_meter,
    needs_topology_pack_migration,
)
from runtime_store.migration.types import (
    Answers,
    Docs,
    ManualTodo,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.topology"

_OPERATOR_CONFIRM = (
    "CONFIRM: plant.grid_meter wurde mit true/true gesetzt. Bitte vor Live prüfen:\n"
    "  1) Sitzt der Zähler direkt am Hausanschluss?\n"
    "  2) Gibt es nur einen Tarif?\n"
    "  3) Regelt ein anderes Gerät selbst auf diesen Zähler?\n"
    "Setze at_house_connection / single_tariff auf false (und korrigiere die Anlage), "
    "falls eine Aussage falsch ist."
)


def detect(docs: Docs) -> bool:
    return needs_topology_pack_migration(
        docs.get("components.json"),
        docs.get("house_profiles.json"),
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    changed_files: list[str] = []
    todos: list[ManualTodo] = []

    components = out.get("components.json")
    if isinstance(components, dict):
        migrated, ids = migrate_components_topology(components)
        if ids:
            out["components.json"] = migrated
            changed_files.append("components.json")

    house = out.get("house_profiles.json")
    if isinstance(house, dict):
        migrated_h, changed_h = migrate_house_profiles_grid_meter(house)
        if changed_h:
            out["house_profiles.json"] = migrated_h
            changed_files.append("house_profiles.json")
            todos.append(ManualTodo(step_id=STEP_ID, text_de=_OPERATOR_CONFIRM))

    return StepResult(
        docs=out,
        changed_files=tuple(changed_files),
        manual_todos=tuple(todos),
    )


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Topologie (regulates_on / grid_meter)",
    files=("components.json", "house_profiles.json"),
    detect=detect,
    apply=apply,
)
