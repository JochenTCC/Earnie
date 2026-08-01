"""Entity-centric EHAL bindings migration (2.4.k; Merker event-triggers removed)."""
from __future__ import annotations

import copy

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
    "nominal_power_kw_name": "get_evcs_nominal_current",
    "ready_by_time_name": "get_evcs_ready_by_time",
    "charge_immediate_name": "charge_immediate_name",
    "get_evcs_limit_soc": "get_evcs_limit_soc",
    "set_evcs_mode": "set_evcs_mode",
    "sens_evcs_connected": "sens_evcs_connected",
    "sens_evcs_soc_act": "sens_evcs_soc_act",
    "sens_evcs_bat_capacity": "sens_evcs_bat_capacity",
    "sens_evcs_nominal_current": "get_evcs_nominal_current",
    "get_evcs_nominal_current": "get_evcs_nominal_current",
    "get_evcs_ready_by_time": "get_evcs_ready_by_time",
}

_LEGACY_SYSTEM_TRIGGER_KEYS: frozenset[str] = frozenset(
    {
        "event_triggers",
        "event_trigger_enabled",
        "event_poll_interval_sec",
    }
)


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
    from ehal.flex_fields import (
        KIND_SENS_POWER_ACT,
        KIND_SET_ENABLE,
        KIND_SET_POWER_SETPOINT,
        flex_field,
    )

    cid = _nonempty(consumer.get("id"))
    inputs = consumer.get("loxone_inputs")
    if isinstance(inputs, dict):
        if cid:
            _put_binding(
                bindings,
                flex_field(cid, KIND_SENS_POWER_ACT),
                inputs.get("power_name"),
            )
        else:
            _put_binding(bindings, "flex.power_name", inputs.get("power_name"))
        alt = _nonempty(inputs.get("alternate_binary_power_name"))
        if alt:
            _put_binding(bindings, "flex.alternate_binary_power_name", alt)
    outputs = consumer.get("loxone_outputs")
    if not isinstance(outputs, dict):
        return
    if cid:
        _put_binding(
            bindings, flex_field(cid, KIND_SET_ENABLE), outputs.get("enable_name")
        )
    else:
        _put_binding(bindings, "flex.enable_name", outputs.get("enable_name"))
    _put_binding(bindings, "pv_follow_name", outputs.get("pv_follow_name"))
    setpoint = (
        outputs.get("power_setpoint_name")
        or outputs.get("set_evcs_max_current")
        or outputs.get("set_evcs_current")
    )
    if consumer.get("type") == "ev":
        _put_binding(bindings, "set_evcs_max_current", setpoint)
    elif cid:
        _put_binding(
            bindings, flex_field(cid, KIND_SET_POWER_SETPOINT), setpoint
        )
    else:
        _put_binding(bindings, "flex.power_setpoint_name", setpoint)
    _put_binding(bindings, "set_evcs_mode", outputs.get("set_evcs_mode"))


def migrate_consumer_legacy_to_ehal_bindings(consumer: dict) -> dict[str, str]:
    """Flatten nested Loxone ``*_name`` nests into ``ehal_bindings`` (§C + transitional)."""
    from ehal.flex_fields import expand_flex_bindings

    bindings: dict[str, str] = {}
    existing = consumer.get("ehal_bindings")
    if isinstance(existing, dict):
        for key, value in existing.items():
            key_s = str(key)
            if key_s == "set_evcs_current":
                field = "set_evcs_max_current"
            elif key_s == "sens_evcs_nominal_current":
                field = "get_evcs_nominal_current"
            else:
                field = key_s
            _put_binding(bindings, field, value)
    sched = consumer.get("charging_schedule")
    if isinstance(sched, dict) and isinstance(sched.get("loxone"), dict):
        _migrate_charging_loxone(sched["loxone"], bindings)
    _migrate_consumer_io(consumer, bindings)
    cid = _nonempty(consumer.get("id"))
    if cid:
        return expand_flex_bindings(bindings, cid)
    return bindings


def _profiles_iterable(house_doc: dict) -> list[dict]:
    profiles = house_doc.get("profiles")
    if isinstance(profiles, dict):
        return list(profiles.values())
    if isinstance(profiles, list):
        return [p for p in profiles if isinstance(p, dict)]
    return []


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


def _strip_entity_event_triggers(house: dict) -> bool:
    """Drop legacy ``event_triggers`` from plant and consumers; return True if changed."""
    changed = False
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else None
    if isinstance(plant, dict) and "event_triggers" in plant:
        plant = dict(plant)
        plant.pop("event_triggers", None)
        house["plant"] = plant
        changed = True
    for profile in _profiles_iterable(house):
        consumers = profile.get("consumers")
        if not isinstance(consumers, list):
            continue
        for index, consumer in enumerate(consumers):
            if not isinstance(consumer, dict) or "event_triggers" not in consumer:
                continue
            cleaned = dict(consumer)
            cleaned.pop("event_triggers", None)
            consumers[index] = cleaned
            changed = True
    return changed


def ensure_migrated(
    house_doc: dict | None,
    config_doc: dict | None,
) -> tuple[dict, dict, bool]:
    """One-shot in-memory migration of blocks/consumer nests → entity bindings."""
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
    if bindings != (plant.get("ehal_bindings") or {}):
        plant["ehal_bindings"] = bindings
        changed = True
    if plant:
        house["plant"] = plant
    if _strip_entity_event_triggers(house):
        changed = True
    if _migrate_all_consumers(house):
        changed = True
    return house, config, changed


def _migrate_all_consumers(house: dict) -> bool:
    from ehal.flex_fields import expand_flex_bindings

    changed = False
    for profile in _profiles_iterable(house):
        consumers = profile.get("consumers")
        if not isinstance(consumers, list):
            continue
        for consumer in consumers:
            if not isinstance(consumer, dict):
                continue
            cid = _nonempty(consumer.get("id"))
            existing = consumer.get("ehal_bindings")
            if isinstance(existing, dict) and any(_nonempty(v) for v in existing.values()):
                if cid:
                    expanded = expand_flex_bindings(existing, cid)
                    if expanded != {
                        str(k): _nonempty(v)
                        for k, v in existing.items()
                        if _nonempty(v)
                    }:
                        consumer["ehal_bindings"] = expanded
                        changed = True
                continue
            migrated = migrate_consumer_legacy_to_ehal_bindings(consumer)
            if migrated:
                consumer["ehal_bindings"] = migrated
                changed = True
    return changed


_PLANT_BLOCK_KEYS: frozenset[str] = frozenset(BLOCKS_TO_EHAL.keys())
_OBSOLETE_BLOCK_KEYS: frozenset[str] = frozenset(
    {"log_filename", "pv_tuning_log_file"}
)


def strip_migrated_config_keys(config_doc: dict | None) -> dict:
    """Drop legacy Merker event-trigger keys; drop migrated/obsolete ``loxone_blocks`` keys."""
    config = copy.deepcopy(config_doc) if isinstance(config_doc, dict) else {}
    system = dict(config.get("system") or {}) if isinstance(config.get("system"), dict) else {}
    if isinstance(config.get("system"), dict) or any(k in system for k in _LEGACY_SYSTEM_TRIGGER_KEYS):
        for key in _LEGACY_SYSTEM_TRIGGER_KEYS:
            system.pop(key, None)
        config["system"] = system
    blocks = config.get("loxone_blocks")
    if isinstance(blocks, dict):
        remaining = {
            key: value
            for key, value in blocks.items()
            if str(key) not in _PLANT_BLOCK_KEYS
            and str(key) not in _OBSOLETE_BLOCK_KEYS
        }
        if remaining:
            config["loxone_blocks"] = remaining
        else:
            config.pop("loxone_blocks", None)
    return config
