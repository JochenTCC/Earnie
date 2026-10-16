"""Step dm4.ehal_bindings — legacy Loxone nests → entity-scoped ehal_bindings."""
from __future__ import annotations

import copy

from house_config.ehal_bindings import (
    ensure_migrated,
    migrate_loxone_blocks_to_plant,
    needs_ehal_bindings_migration,
    strip_migrated_config_keys,
)
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.ehal_bindings"


def detect(docs: Docs) -> bool:
    return needs_ehal_bindings_migration(
        docs.get("house_profiles.json"),
        docs.get("config.json"),
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    house = out.get("house_profiles.json")
    config = out.get("config.json")
    if not isinstance(house, dict):
        return StepResult(docs=out, changed_files=())

    house_doc = copy.deepcopy(house)
    config_doc = copy.deepcopy(config) if isinstance(config, dict) else None

    if isinstance(config_doc, dict):
        blocks = config_doc.get("loxone_blocks")
        if isinstance(blocks, dict) and blocks:
            plant = (
                dict(house_doc.get("plant") or {})
                if isinstance(house_doc.get("plant"), dict)
                else {}
            )
            bindings = (
                dict(plant.get("ehal_bindings") or {})
                if isinstance(plant.get("ehal_bindings"), dict)
                else {}
            )
            for field, addr in migrate_loxone_blocks_to_plant(blocks).items():
                if field not in bindings or not str(bindings.get(field) or "").strip():
                    bindings[field] = addr
            plant["ehal_bindings"] = bindings
            house_doc["plant"] = plant
            config_doc = dict(config_doc)
            config_doc.pop("loxone_blocks", None)

    try:
        house_out, config_out, changed = ensure_migrated(
            house_doc,
            config_doc,
            strip_legacy=True,
            migrate_secrets=False,
        )
    except ValueError as exc:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(Blocker(step_id=STEP_ID, message_de=str(exc)),),
        )
    changed_files: list[str] = []
    if changed or house_out != house:
        out["house_profiles.json"] = house_out
        changed_files.append("house_profiles.json")
    if isinstance(config_out, dict):
        stripped = strip_migrated_config_keys(config_out)
        if "config.json" in out and stripped != out.get("config.json"):
            out["config.json"] = stripped
            if "config.json" not in changed_files:
                changed_files.append("config.json")
        elif config_doc is not None and config_out != config:
            out["config.json"] = config_out
            if "config.json" not in changed_files:
                changed_files.append("config.json")
    return StepResult(docs=out, changed_files=tuple(changed_files))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="EHAL-Bindings (Loxone-Nester → Entity-Bindings)",
    files=("house_profiles.json", "config.json"),
    detect=detect,
    apply=apply,
)
