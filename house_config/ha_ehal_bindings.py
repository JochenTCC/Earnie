"""HA entity IDs on Pattern B (2.6.g): migrate / aggregate / apply."""
from __future__ import annotations

import copy

from ehal.models import canonicalize_ha_entity_keys
from integrations.ha_adapter import (
    SETPOINT_FIELDS,
    TELEMETRY_ENERGY_OPTIONAL,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
)

# EV-scoped §C keys (same consumer placement as Loxone Pattern B).
HA_EV_FIELDS: frozenset[str] = frozenset(
    {
        "sens_evcs_active_power",
        "set_evcs_max_current",
        "set_evcs_mode",
    }
)

HA_ALL_FIELDS: tuple[str, ...] = (
    TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL + TELEMETRY_ENERGY_OPTIONAL + SETPOINT_FIELDS
)

HA_PLANT_FIELDS: frozenset[str] = frozenset(
    field for field in HA_ALL_FIELDS if field not in HA_EV_FIELDS
)


def _nonempty(value: object) -> str:
    return str(value or "").strip()


def _profiles_iterable(house_doc: dict) -> list[dict]:
    profiles = house_doc.get("profiles")
    if isinstance(profiles, dict):
        return list(profiles.values())
    if isinstance(profiles, list):
        return [p for p in profiles if isinstance(p, dict)]
    return []


def _is_ev_consumer(consumer: dict) -> bool:
    if str(consumer.get("type") or "") == "ev":
        return True
    sched = consumer.get("charging_schedule")
    return isinstance(sched, dict) and bool(sched.get("enabled"))


def find_first_ev_consumer(house_doc: dict | None) -> dict | None:
    """First EV/wallbox consumer; prefer profile id ``live`` when present."""
    house = house_doc if isinstance(house_doc, dict) else {}
    profiles = house.get("profiles")
    ordered: list[dict] = []
    if isinstance(profiles, dict):
        if isinstance(profiles.get("live"), dict):
            ordered.append(profiles["live"])
        ordered.extend(
            p for key, p in profiles.items() if key != "live" and isinstance(p, dict)
        )
    else:
        ordered = _profiles_iterable(house)
    for profile in ordered:
        consumers = profile.get("consumers")
        if not isinstance(consumers, list):
            continue
        for consumer in consumers:
            if isinstance(consumer, dict) and _is_ev_consumer(consumer):
                return consumer
    return None


def _binding_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): _nonempty(v)
        for k, v in raw.items()
        if _nonempty(v)
    }


def _put_empty_only(target: dict[str, str], field: str, entity_id: str) -> bool:
    if not field or not entity_id:
        return False
    if _nonempty(target.get(field)):
        return False
    target[field] = entity_id
    return True


def _ensure_plant(house: dict) -> dict:
    plant = dict(house.get("plant") or {}) if isinstance(house.get("plant"), dict) else {}
    house["plant"] = plant
    return plant


def migrate_ha_entities_to_house(
    house_doc: dict | None,
    entities: dict | None,
) -> tuple[dict, bool]:
    """Empty-only merge of flat ``ehal.ha.entities`` into Pattern B bindings."""
    house = copy.deepcopy(house_doc) if isinstance(house_doc, dict) else {}
    if not isinstance(entities, dict) or not entities:
        return house, False
    canonical = canonicalize_ha_entity_keys(
        {str(k): str(v) for k, v in entities.items() if _nonempty(v)}
    )
    if not canonical:
        return house, False

    plant = _ensure_plant(house)
    plant_bindings = _binding_map(plant.get("ehal_bindings"))
    ev_consumer = find_first_ev_consumer(house)
    ev_bindings = _binding_map(ev_consumer.get("ehal_bindings") if ev_consumer else None)
    changed = False

    for field, entity_id in canonical.items():
        eid = _nonempty(entity_id)
        if not eid:
            continue
        if field in HA_EV_FIELDS and ev_consumer is not None:
            if _put_empty_only(ev_bindings, field, eid):
                changed = True
        else:
            if _put_empty_only(plant_bindings, field, eid):
                changed = True

    if plant_bindings != _binding_map(plant.get("ehal_bindings")):
        plant["ehal_bindings"] = plant_bindings
        changed = True
    if ev_consumer is not None and ev_bindings != _binding_map(
        ev_consumer.get("ehal_bindings")
    ):
        ev_consumer["ehal_bindings"] = ev_bindings
        changed = True
    return house, changed


def aggregate_ha_entities(house_doc: dict | None) -> dict[str, str]:
    """Flat field→entity_id map for ``HaAdapter`` from plant + first EV consumer."""
    house = house_doc if isinstance(house_doc, dict) else {}
    out: dict[str, str] = {}
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    plant_bindings = _binding_map(plant.get("ehal_bindings"))
    for field in HA_ALL_FIELDS:
        if field in HA_EV_FIELDS:
            continue
        value = plant_bindings.get(field)
        if value:
            out[field] = value
    # EV keys: prefer consumer; fall back to plant (migrate without EV consumer).
    ev_consumer = find_first_ev_consumer(house)
    ev_bindings = _binding_map(ev_consumer.get("ehal_bindings") if ev_consumer else None)
    for field in HA_EV_FIELDS:
        value = ev_bindings.get(field) or plant_bindings.get(field)
        if value:
            out[field] = value
    return canonicalize_ha_entity_keys(out)


def apply_ha_entities_to_house(
    house_doc: dict | None,
    entities: dict[str, str] | None,
) -> dict:
    """Overwrite HA-scoped bindings from a flat map (HITL giant-form save)."""
    house = copy.deepcopy(house_doc) if isinstance(house_doc, dict) else {}
    canonical = canonicalize_ha_entity_keys(
        {str(k): str(v) for k, v in (entities or {}).items() if _nonempty(v)}
    )
    plant = _ensure_plant(house)
    plant_bindings = _binding_map(plant.get("ehal_bindings"))
    for field in HA_PLANT_FIELDS:
        if field in canonical:
            plant_bindings[field] = canonical[field]
        else:
            plant_bindings.pop(field, None)

    ev_consumer = find_first_ev_consumer(house)
    if ev_consumer is not None:
        ev_bindings = _binding_map(ev_consumer.get("ehal_bindings"))
        for field in HA_EV_FIELDS:
            plant_bindings.pop(field, None)
            if field in canonical:
                ev_bindings[field] = canonical[field]
            else:
                ev_bindings.pop(field, None)
        ev_consumer["ehal_bindings"] = ev_bindings
    else:
        for field in HA_EV_FIELDS:
            if field in canonical:
                plant_bindings[field] = canonical[field]
            else:
                plant_bindings.pop(field, None)

    plant["ehal_bindings"] = plant_bindings
    return house


def strip_ha_entities_from_config(config_doc: dict | None) -> tuple[dict, bool]:
    """Clear ``ehal.ha.entities`` (keep sign / URL / token)."""
    config = copy.deepcopy(config_doc) if isinstance(config_doc, dict) else {}
    ehal = config.get("ehal")
    if not isinstance(ehal, dict):
        return config, False
    ha = ehal.get("ha")
    if not isinstance(ha, dict) or "entities" not in ha:
        return config, False
    entities = ha.get("entities")
    if isinstance(entities, dict) and not any(_nonempty(v) for v in entities.values()):
        return config, False
    if entities == {}:
        return config, False
    ha = dict(ha)
    ha["entities"] = {}
    ehal = dict(ehal)
    ehal["ha"] = ha
    config["ehal"] = ehal
    return config, True


def load_house_profiles_for_ha() -> dict | None:
    """Best-effort load of house_profiles.json for live HA aggregation."""
    import logging
    import os

    logger = logging.getLogger(__name__)
    try:
        from house_config.profiles_store import load_house_profiles_document
        from runtime_store.persist_paths import resolve_house_profiles_json_path

        path = resolve_house_profiles_json_path()
        if not path or not os.path.isfile(path):
            return None
        return load_house_profiles_document(path)
    except Exception as exc:
        logger.warning("house_profiles for HA bindings not loaded: %s", exc)
        return None
