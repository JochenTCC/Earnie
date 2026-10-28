"""Step dm4.conversion_efficiency — split inverter/battery efficiency."""
from __future__ import annotations

import copy

from house_config.inverter import needs_conversion_efficiency_migration
from house_config.migrate_conversion_efficiency import (
    migrate_components_conversion_efficiency,
)
from runtime_store.migration.types import (
    Answers,
    Docs,
    ManualTodo,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.conversion_efficiency"


def detect(docs: Docs) -> bool:
    components = docs.get("components.json")
    return isinstance(components, dict) and needs_conversion_efficiency_migration(
        components
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    components = out.get("components.json")
    if not isinstance(components, dict):
        return StepResult(docs=out, changed_files=())
    migrated, changed = migrate_components_conversion_efficiency(components)
    if changed:
        out["components.json"] = migrated
        return StepResult(docs=out, changed_files=("components.json",))
    return StepResult(docs=out, changed_files=())


def _fmt(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def _efficiency_by_id(components: object, key: str, eta_key: str) -> dict[str, float]:
    items = components.get(key) if isinstance(components, dict) else None
    return {
        str(item.get("id") or "?"): float(item[eta_key])
        for item in items or []
        if isinstance(item, dict) and item.get(eta_key) not in (None, "")
    }


def manual_todos(before: Docs, after: Docs) -> list[ManualTodo]:
    """Say how the lumped battery efficiency was split (2.6 → 2.7)."""
    components = after.get("components.json")
    old_batt = _efficiency_by_id(
        before.get("components.json"), "batteries", "battery_efficiency"
    )
    new_batt = _efficiency_by_id(components, "batteries", "battery_efficiency")
    eta_inv = _efficiency_by_id(components, "inverters", "efficiency")
    lines = []
    for bat in (components or {}).get("batteries") or []:
        if not isinstance(bat, dict):
            continue
        bat_id = str(bat.get("id") or "?")
        if bat_id not in old_batt or old_batt[bat_id] == new_batt.get(bat_id):
            continue
        inv_id = str(bat.get("inverter_id") or "").strip()
        inv_part = (
            f"η_inv {_fmt(eta_inv[inv_id])} (`{inv_id}`) × " if inv_id in eta_inv else ""
        )
        lines.append(
            f"`{bat_id}`: {_fmt(old_batt[bat_id])} → {inv_part}"
            f"η_batt {_fmt(new_batt[bat_id])}"
        )
    if not lines:
        return []
    return [
        ManualTodo(
            step_id=STEP_ID,
            text_de=(
                "Wirkungsgrad aufgeteilt: Der bisherige Batterie-Wirkungsgrad galt für "
                "den ganzen Pfad. Earnie rechnet jetzt mit η_inv (Wechselrichter) × "
                "η_batt (Batterie), das Produkt bleibt gleich: "
                + "; ".join(lines)
                + ". η_inv ist eine Vorgabe der Migration. Wer den Wert des "
                "Wechselrichters kennt, ändert ihn im Hauskonfigurator unter "
                "„Wechselrichter“ und passt η_batt an der Batterie so an, dass das "
                "Produkt wieder dem Wirkungsgrad pro Richtung entspricht."
            ),
        )
    ]


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Wirkungsgrade (η_inv / η_batt)",
    files=("components.json",),
    detect=detect,
    apply=apply,
    manual_todos=manual_todos,
)
