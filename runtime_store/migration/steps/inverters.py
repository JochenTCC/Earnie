"""Step dm4.inverters — batteries[].kind → inverters[]."""
from __future__ import annotations

import copy

from house_config.inverter import needs_inverter_migration
from house_config.migrate_inverters import migrate_components_inverters
from runtime_store.migration.types import (
    Answers,
    Docs,
    ManualTodo,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.inverters"


def detect(docs: Docs) -> bool:
    components = docs.get("components.json")
    return isinstance(components, dict) and needs_inverter_migration(components)


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    components = out.get("components.json")
    if not isinstance(components, dict):
        return StepResult(docs=out, changed_files=())
    migrated, changed = migrate_components_inverters(components)
    if changed:
        out["components.json"] = migrated
        return StepResult(docs=out, changed_files=("components.json",))
    return StepResult(docs=out, changed_files=())


def _pv_ids_without_inverter(docs: Docs) -> list[str]:
    components = docs.get("components.json")
    pv_systems = components.get("pv_systems") if isinstance(components, dict) else None
    return [
        str(pv.get("id") or "?")
        for pv in pv_systems or []
        if isinstance(pv, dict) and not str(pv.get("inverter_id") or "").strip()
    ]


def manual_todos(before: Docs, after: Docs) -> list[ManualTodo]:
    """The migration cannot know which inverter a PV system feeds (issue #61)."""
    assigned = _pv_ids_without_inverter(before)
    if not assigned or _pv_ids_without_inverter(after):
        return []
    return [
        ManualTodo(
            step_id=STEP_ID,
            text_de=(
                "PV-Anlagen " + ", ".join(f"`{pv_id}`" for pv_id in assigned)
                + " wurden dem Haupt-Wechselrichter `wr_main` zugeordnet (Vorgabe der "
                "Migration, Earnie kennt die Verschaltung nicht). Speist eine Anlage "
                "über einen eigenen Wechselrichter ein (z. B. Volleinspeiser mit "
                "eigenem Zähler oder eine Anlage, die direkt ins Haus einspeist), im "
                "Hauskonfigurator unter „Wechselrichter“ den Wechselrichter anlegen "
                "und die Anlage unter „PV-Felder“ zuordnen."
            ),
        )
    ]


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Wechselrichter-Entity (inverters[])",
    files=("components.json",),
    detect=detect,
    apply=apply,
    manual_todos=manual_todos,
)
