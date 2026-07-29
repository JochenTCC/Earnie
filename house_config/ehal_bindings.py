"""Entity-centric EHAL bindings + event-trigger migration (2.4.k)."""
from __future__ import annotations

import copy
from typing import Any

from integrations.loxone_ehal_mapping import EHAL_TO_BLOCKS

# Inverse of plant EHAL_TO_BLOCKS for §C keys only (not legacy unprefixed aliases).
BLOCKS_TO_EHAL: dict[str, str] = {
    block: field
    for field, block in EHAL_TO_BLOCKS.items()
    if field.startswith(("sens_", "set_", "get_"))
}

_EV_CHARGING_TO_EHAL: dict[str, str] = {
    "plugged_in_name": "sens_evcs_connected",
    "actual_soc_name": "sens_evcs_soc_act",
    "battery_capacity_kwh_name": "sens_evcs_bat_capacity",
    "nominal_power_kw_name": "sens_evcs_nominal_current",
    "ready_by_time_name": "get_evcs_ready_by_time",
    "charge_immediate_name": "charge_immediate_name",
    "get_evcs_limit_soc": "get_evcs_limit_soc",
    "set_evcs_mode": "set_evcs_mode",
    "sens_evcs_connected": "sens_evcs_connected",
    "sens_evcs_soc_act": "sens_evcs_soc_act",
    "sens_evcs_bat_capacity": "sens_evcs_bat_capacity",
    "sens_evcs_nominal_current": "sens_evcs_nominal_current",
    "get_evcs_ready_by_time": "get_evcs_ready_by_time",
}


def _nonempty(value: object) -> str:
    return str(value or "").strip()


def _put_binding(bindings: dict[str, str], field: str, address: object) -> None:
    name = _nonempty(address)
    if field and name and field not in bindings:
        bindings[field] = name


def migrate_loxone_blocks_to_plant(blocks: dict | None) -> dict[str, str]:
    """Map legacy ``loxone_blocks`` role keys → ``plant.ehal_bindings`` (§C)."""
    out: dict[str, str] = {}
    if not isinstance(blocks, dict):
        return out
    for block_key, address in blocks.items():
        field = BLOCKS_TO_EHAL.get(str(block_key))
        if field:
            _put_binding(out, field, address)
    return out


def _migrate_charging_loxone(lox: dict, bindings: dict[str, str]) -> None:
    for legacy_key, ehal_field in _EV_CHARGING_TO_EHAL.items():
        if legacy_key in lox:
            _put_binding(bindings, ehal_field, lox.get(legacy_key))


def _migrate_consumer_io(consumer: dict, bindings: dict[str, str]) -> None:
    inputs = consumer.get("loxone_inputs")
    if isinstance(inputs, dict):
        _put_binding(bindings, "flex.power_name", inputs.get("power_name"))
        alt = _nonempty(inputs.get("alternate_binary_power_name"))
        if alt:
            _put_binding(bindings, "flex.alternate_binary_power_name", alt)
    outputs = consumer.get("loxone_outputs")
    if not isinstance(outputs, dict):
        return
    _put_binding(bindings, "flex.enable_name", outputs.get("enable_name"))
    _put_binding(bindings, "pv_follow_name", outputs.get("pv_follow_name"))
    setpoint = outputs.get("power_setpoint_name") or outputs.get("set_evcs_current")
    if consumer.get("type") == "ev":
        _put_binding(bindings, "set_evcs_current", setpoint)
    else:
        _put_binding(bindings, "flex.power_setpoint_name", setpoint)
    _put_binding(bindings, "set_evcs_mode", outputs.get("set_evcs_mode"))


def migrate_consumer_legacy_to_ehal_bindings(consumer: dict) -> dict[str, str]:
    """Flatten nested Loxone ``*_name`` nests into ``ehal_bindings`` (§C + transitional)."""
    bindings: dict[str, str] = {}
    existing = consumer.get("ehal_bindings")
    if isinstance(existing, dict):
        for key, value in existing.items():
            _put_binding(bindings, str(key), value)
    sched = consumer.get("charging_schedule")
    if isinstance(sched, dict) and isinstance(sched.get("loxone"), dict):
        _migrate_charging_loxone(sched["loxone"], bindings)
    _migrate_consumer_io(consumer, bindings)
    return bindings


def _binding_field_for_address(bindings: dict[str, str], address: str) -> str:
    target = _nonempty(address)
    if not target:
        return ""
    for field, value in bindings.items():
        if _nonempty(value) == target:
            return str(field)
    return ""


def migrate_config_triggers_to_plant(
    triggers: list | None,
    plant_bindings: dict | None,
) -> tuple[list[dict], dict[str, str]]:
    """Move ``system.event_triggers`` onto plant; stub ``event.<id>`` when needed."""
    bindings = {
        str(k): _nonempty(v)
        for k, v in (plant_bindings or {}).items()
        if _nonempty(v)
    }
    out: list[dict] = []
    if not isinstance(triggers, list):
        return out, bindings
    for index, raw in enumerate(triggers):
        if not isinstance(raw, dict):
            continue
        trigger_id = _nonempty(raw.get("id")) or f"trigger_{index}"
        address = _nonempty(raw.get("loxone_name"))
        ehal_field = _nonempty(raw.get("ehal_field"))
        if not ehal_field:
            ehal_field = _binding_field_for_address(bindings, address)
        if not ehal_field:
            ehal_field = f"event.{trigger_id}"
        if address:
            _put_binding(bindings, ehal_field, address)
        out.append(
            {
                "id": trigger_id,
                "ehal_field": ehal_field,
                "signal_type": _nonempty(raw.get("signal_type")).lower() or "binary",
                "on_change": _nonempty(raw.get("on_change")).lower() or "any",
                "label": _nonempty(raw.get("label")) or trigger_id,
            }
        )
    return out, bindings


def _profiles_iterable(house_doc: dict) -> list[dict]:
    profiles = house_doc.get("profiles")
    if isinstance(profiles, dict):
        return list(profiles.values())
    if isinstance(profiles, list):
        return [p for p in profiles if isinstance(p, dict)]
    return []


def _consumers_for_profile(house_doc: dict, profile_id: str | None) -> list[dict]:
    consumers: list[dict] = []
    for profile in _profiles_iterable(house_doc):
        if profile_id and str(profile.get("id") or "") != profile_id:
            continue
        raw = profile.get("consumers") or []
        if isinstance(raw, list):
            consumers.extend(c for c in raw if isinstance(c, dict))
    return consumers


def _resolve_trigger_spec(raw: dict, bindings: dict[str, str], index: int) -> dict:
    from settings.system_settings import normalize_event_trigger

    ehal_field = _nonempty(raw.get("ehal_field"))
    address = _nonempty(bindings.get(ehal_field)) or _nonempty(raw.get("loxone_name"))
    return normalize_event_trigger(
        {
            "id": raw.get("id"),
            "loxone_name": address,
            "signal_type": raw.get("signal_type"),
            "on_change": raw.get("on_change"),
            "label": raw.get("label"),
        },
        index,
    )


def aggregate_event_triggers(
    house_profiles_doc: dict | None,
    profile_id: str | None = None,
) -> list[dict]:
    """Flatten plant + consumer triggers; resolve ``loxone_name`` from bindings."""
    house = house_profiles_doc if isinstance(house_profiles_doc, dict) else {}
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    plant_bindings = plant.get("ehal_bindings") if isinstance(plant.get("ehal_bindings"), dict) else {}
    specs: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(plant.get("event_triggers") or []):
        if not isinstance(raw, dict):
            continue
        spec = _resolve_trigger_spec(raw, plant_bindings, index)
        if spec["id"] in seen:
            raise ValueError(
                f"Kritischer Konfigurationsfehler: event_triggers enthält "
                f"doppelte id '{spec['id']}'."
            )
        seen.add(spec["id"])
        specs.append(spec)
    offset = len(specs)
    for c_index, consumer in enumerate(_consumers_for_profile(house, profile_id)):
        bindings = consumer.get("ehal_bindings")
        if not isinstance(bindings, dict):
            bindings = {}
        for t_index, raw in enumerate(consumer.get("event_triggers") or []):
            if not isinstance(raw, dict):
                continue
            spec = _resolve_trigger_spec(raw, bindings, offset + c_index + t_index)
            if spec["id"] in seen:
                raise ValueError(
                    f"Kritischer Konfigurationsfehler: event_triggers enthält "
                    f"doppelte id '{spec['id']}'."
                )
            seen.add(spec["id"])
            specs.append(spec)
    return specs


def resolve_plant_binding(house_doc: dict | None, ehal_field: str, config_doc: dict | None = None) -> str:
    """Prefer ``plant.ehal_bindings``; dual-read ``loxone_blocks`` only while plant empty."""
    field = _nonempty(ehal_field)
    house = house_doc if isinstance(house_doc, dict) else {}
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    bindings = plant.get("ehal_bindings") if isinstance(plant.get("ehal_bindings"), dict) else {}
    value = _nonempty(bindings.get(field))
    if value:
        return value
    if any(_nonempty(v) for v in bindings.values()):
        return ""
    config = config_doc if isinstance(config_doc, dict) else {}
    blocks = config.get("loxone_blocks") if isinstance(config.get("loxone_blocks"), dict) else {}
    block_key = EHAL_TO_BLOCKS.get(field, "")
    return _nonempty(blocks.get(block_key)) if block_key else ""


def _plant_bindings_empty(plant: dict) -> bool:
    bindings = plant.get("ehal_bindings")
    return not (isinstance(bindings, dict) and any(_nonempty(v) for v in bindings.values()))


def _plant_triggers_empty(plant: dict) -> bool:
    triggers = plant.get("event_triggers")
    return not (isinstance(triggers, list) and triggers)


def ensure_migrated(
    house_doc: dict | None,
    config_doc: dict | None,
) -> tuple[dict, dict, bool]:
    """One-shot in-memory migration of blocks/triggers/consumer nests → entity bindings."""
    house = copy.deepcopy(house_doc) if isinstance(house_doc, dict) else {}
    config = copy.deepcopy(config_doc) if isinstance(config_doc, dict) else {}
    changed = False
    plant = dict(house.get("plant") or {}) if isinstance(house.get("plant"), dict) else {}
    bindings = {
        str(k): _nonempty(v)
        for k, v in (plant.get("ehal_bindings") or {}).items()
        if _nonempty(v)
    }
    blocks = config.get("loxone_blocks") if isinstance(config.get("loxone_blocks"), dict) else {}
    if blocks and _plant_bindings_empty(plant):
        migrated = migrate_loxone_blocks_to_plant(blocks)
        if migrated:
            bindings.update(migrated)
            changed = True
    system = config.get("system") if isinstance(config.get("system"), dict) else {}
    config_triggers = system.get("event_triggers")
    if isinstance(config_triggers, list) and config_triggers and _plant_triggers_empty(plant):
        new_triggers, bindings = migrate_config_triggers_to_plant(config_triggers, bindings)
        plant["event_triggers"] = new_triggers
        changed = True
    if bindings != (plant.get("ehal_bindings") or {}):
        plant["ehal_bindings"] = bindings
        changed = True
    if plant:
        house["plant"] = plant
    if _migrate_all_consumers(house):
        changed = True
    return house, config, changed


def _migrate_all_consumers(house: dict) -> bool:
    changed = False
    for profile in _profiles_iterable(house):
        consumers = profile.get("consumers")
        if not isinstance(consumers, list):
            continue
        for consumer in consumers:
            if not isinstance(consumer, dict):
                continue
            existing = consumer.get("ehal_bindings")
            if isinstance(existing, dict) and any(_nonempty(v) for v in existing.values()):
                continue
            migrated = migrate_consumer_legacy_to_ehal_bindings(consumer)
            if migrated:
                consumer["ehal_bindings"] = migrated
                changed = True
    return changed


_PLANT_BLOCK_KEYS: frozenset[str] = frozenset(BLOCKS_TO_EHAL.keys())


def strip_migrated_config_keys(config_doc: dict | None) -> dict:
    """Clear ``system.event_triggers`` and plant markers from ``loxone_blocks``."""
    config = copy.deepcopy(config_doc) if isinstance(config_doc, dict) else {}
    system = dict(config.get("system") or {}) if isinstance(config.get("system"), dict) else {}
    if "event_triggers" in system:
        system["event_triggers"] = []
        config["system"] = system
    blocks = config.get("loxone_blocks")
    if isinstance(blocks, dict):
        config["loxone_blocks"] = {
            key: value
            for key, value in blocks.items()
            if str(key) not in _PLANT_BLOCK_KEYS
        }
    return config


def house_has_entity_triggers(house_doc: dict | None) -> bool:
    house = house_doc if isinstance(house_doc, dict) else {}
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    if isinstance(plant.get("event_triggers"), list) and plant["event_triggers"]:
        return True
    for consumer in _consumers_for_profile(house, None):
        triggers = consumer.get("event_triggers")
        if isinstance(triggers, list) and triggers:
            return True
    return False
