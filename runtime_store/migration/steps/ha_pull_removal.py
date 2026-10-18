"""Step dm4.ha_pull_removal — drop HA pull transport (Binding P5e).

Detect-based in-model step: remove ``ehal.ha.transport``, discard stored HA
``entity_id`` values in ``ehal_bindings`` (keys stay as activation), and clear
legacy flat ``ehal.ha.entities``. Leftover ``transport`` after this step fails
loud in loaders (see ``runtime_store.ehal_setup.reject_leftover_ha_transport``).
"""
from __future__ import annotations

import copy
from typing import Any

from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    ManualTodo,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.ha_pull_removal"

# HA entity_id domains historically stored in ehal_bindings / flat entities.
_HA_ENTITY_DOMAINS = frozenset(
    {
        "sensor",
        "number",
        "select",
        "input_number",
        "binary_sensor",
        "input_boolean",
        "switch",
    }
)


def looks_like_ha_entity_id(value: object) -> bool:
    text = str(value or "").strip()
    if not text or "." not in text:
        return False
    domain, _, object_id = text.partition(".")
    return domain.lower() in _HA_ENTITY_DOMAINS and bool(object_id.strip())


def _ha_block(docs: Docs) -> dict[str, Any] | None:
    config = docs.get("config.json")
    if not isinstance(config, dict):
        return None
    ehal = config.get("ehal")
    if not isinstance(ehal, dict):
        return None
    ha = ehal.get("ha")
    return ha if isinstance(ha, dict) else None


def _has_transport(docs: Docs) -> bool:
    ha = _ha_block(docs)
    return isinstance(ha, dict) and "transport" in ha


def _bindings_have_ha_entity_ids(bindings: Any) -> bool:
    if not isinstance(bindings, dict):
        return False
    return any(looks_like_ha_entity_id(v) for v in bindings.values())


def _house_has_ha_entity_ids(house: Any) -> bool:
    if not isinstance(house, dict):
        return False
    plant = house.get("plant")
    if isinstance(plant, dict) and _bindings_have_ha_entity_ids(
        plant.get("ehal_bindings")
    ):
        return True
    profiles = house.get("profiles")
    items = profiles.values() if isinstance(profiles, dict) else profiles
    if not isinstance(items, (list, tuple)) and not isinstance(profiles, dict):
        return False
    for profile in items:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if isinstance(consumer, dict) and _bindings_have_ha_entity_ids(
                consumer.get("ehal_bindings")
            ):
                return True
    return False


def _components_have_ha_entity_ids(components: Any) -> bool:
    if not isinstance(components, dict):
        return False
    for section in ("batteries", "inverters", "pv_systems"):
        for entity in components.get(section) or []:
            if isinstance(entity, dict) and _bindings_have_ha_entity_ids(
                entity.get("ehal_bindings")
            ):
                return True
    return False


def _flat_entities_nonempty(docs: Docs) -> bool:
    ha = _ha_block(docs)
    if not isinstance(ha, dict):
        return False
    entities = ha.get("entities")
    if not isinstance(entities, dict):
        return False
    return any(str(v or "").strip() for v in entities.values())


def detect(docs: Docs) -> bool:
    return (
        _has_transport(docs)
        or _flat_entities_nonempty(docs)
        or _house_has_ha_entity_ids(docs.get("house_profiles.json"))
        or _components_have_ha_entity_ids(docs.get("components.json"))
    )


def _clear_ha_entity_id_values(bindings: dict | None) -> dict[str, str]:
    """Keep activation keys; blank values that look like HA entity_ids."""
    if not isinstance(bindings, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in bindings.items():
        text_key = str(key or "").strip()
        if not text_key:
            continue
        if looks_like_ha_entity_id(value):
            out[text_key] = ""
        else:
            out[text_key] = str(value or "").strip()
    return out


def _clear_house_ha_entity_ids(house_doc: dict) -> dict:
    """Clear HA entity_id values; reuse Loxone clear helpers when all values are IDs."""
    # When backend stored only HA ids, clear_binding_values is equivalent and simpler.
    # Mixed packs (unlikely): only blank HA-looking values.
    house = copy.deepcopy(house_doc)
    plant = house.get("plant")
    if isinstance(plant, dict) and isinstance(plant.get("ehal_bindings"), dict):
        plant = dict(plant)
        plant["ehal_bindings"] = _clear_ha_entity_id_values(plant.get("ehal_bindings"))
        house["plant"] = plant

    def _clear_profile(profile: dict) -> dict:
        profile = dict(profile)
        consumers = []
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                consumers.append(consumer)
                continue
            consumer = dict(consumer)
            if isinstance(consumer.get("ehal_bindings"), dict):
                consumer["ehal_bindings"] = _clear_ha_entity_id_values(
                    consumer.get("ehal_bindings")
                )
            consumers.append(consumer)
        profile["consumers"] = consumers
        return profile

    profiles = house.get("profiles")
    if isinstance(profiles, dict):
        house["profiles"] = {
            pid: _clear_profile(p) if isinstance(p, dict) else p
            for pid, p in profiles.items()
        }
    elif isinstance(profiles, list):
        house["profiles"] = [
            _clear_profile(p) if isinstance(p, dict) else p for p in profiles
        ]
    return house


def _clear_components_ha_entity_ids(components_doc: dict) -> dict:
    doc = copy.deepcopy(components_doc)
    for section in ("batteries", "inverters", "pv_systems"):
        entities = doc.get(section)
        if not isinstance(entities, list):
            continue
        out_entities = []
        for entity in entities:
            if not isinstance(entity, dict):
                out_entities.append(entity)
                continue
            entity = dict(entity)
            if isinstance(entity.get("ehal_bindings"), dict):
                entity["ehal_bindings"] = _clear_ha_entity_id_values(
                    entity.get("ehal_bindings")
                )
            out_entities.append(entity)
        doc[section] = out_entities
    return doc


def _strip_transport_and_flat_entities(config: dict) -> tuple[dict, bool]:
    ehal = config.get("ehal")
    if not isinstance(ehal, dict):
        return config, False
    ha = ehal.get("ha")
    if not isinstance(ha, dict):
        return config, False
    changed = False
    ha_out = dict(ha)
    if "transport" in ha_out:
        ha_out.pop("transport", None)
        changed = True
    entities = ha_out.get("entities")
    if isinstance(entities, dict) and any(str(v or "").strip() for v in entities.values()):
        ha_out["entities"] = {}
        changed = True
    if not changed:
        return config, False
    ehal_out = dict(ehal)
    ehal_out["ha"] = ha_out
    out = dict(config)
    out["ehal"] = ehal_out
    return out, True


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    changed: list[str] = []

    config = out.get("config.json")
    if isinstance(config, dict):
        updated, did = _strip_transport_and_flat_entities(config)
        if did:
            stamp_data_model(updated)
            out["config.json"] = updated
            changed.append("config.json")

    house = out.get("house_profiles.json")
    if isinstance(house, dict) and _house_has_ha_entity_ids(house):
        # Prefer full clear when every non-empty value is an HA entity_id.
        updated_h = _clear_house_ha_entity_ids(house)
        if updated_h != house:
            stamp_data_model(updated_h)
            out["house_profiles.json"] = updated_h
            changed.append("house_profiles.json")

    components = out.get("components.json")
    if isinstance(components, dict) and _components_have_ha_entity_ids(components):
        updated_c = _clear_components_ha_entity_ids(components)
        if updated_c != components:
            stamp_data_model(updated_c)
            out["components.json"] = updated_c
            changed.append("components.json")

    return StepResult(docs=out, changed_files=tuple(changed))


def manual_todos(before: Docs, after: Docs) -> list[ManualTodo]:
    del before, after
    return [
        ManualTodo(
            step_id=STEP_ID,
            text_de=(
                "Home Assistant: nach der Migration unter Echtzeit-Umgebung → EHAL-Com "
                "→ Signalliste das YAML-Paket herunterladen und in HA einbinden "
                "(ENTITY_* Platzhalter setzen). Pull-/Entity-Mapping entfällt; "
                "Earnie speichert keine entity_id mehr."
            ),
        )
    ]


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="HA Pull-Transport entfernen (Push only)",
    files=("config.json", "house_profiles.json", "components.json"),
    detect=detect,
    apply=apply,
    questions=(),
    manual_todos=manual_todos,
)
