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

_THERMAL_LOXONE_TO_EHAL: dict[str, str] = {
    "actual_temp_name": "sens_temperature_water",
    "setpoint_temp_name": "get_temperature_water_setpoint",
    "tolerance_c_name": "get_temperature_tolerance_c",
    "heating_active_name": "sens_heating_active",
    "ambient_temp_name": "sens_temperature_outside",
}

THERMAL_RC_EHAL_FIELDS: tuple[str, ...] = (
    "sens_temperature_water",
    "get_temperature_water_setpoint",
    "get_temperature_tolerance_c",
    "sens_heating_active",
)

_INPUT_MARKER_KEYS: frozenset[str] = frozenset(
    {
        "power_name",
        "alternate_binary_power_name",
        "sens_evcs_active_power",
        "flex.power_name",
        "sens_filter_active",
    }
)
_OUTPUT_MARKER_KEYS: frozenset[str] = frozenset(
    {
        "enable_name",
        "power_setpoint_name",
        "pv_follow_name",
        "set_evcs_max_current",
        "set_evcs_current",
        "set_evcs_mode",
        "flex.enable_name",
        "flex.power_setpoint_name",
    }
)

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


def _migrate_thermal_loxone(consumer: dict, bindings: dict[str, str]) -> None:
    thermal = consumer.get("thermal_control")
    if not isinstance(thermal, dict):
        return
    lox = thermal.get("loxone")
    if not isinstance(lox, dict):
        return
    for legacy_key, ehal_field in _THERMAL_LOXONE_TO_EHAL.items():
        if legacy_key in lox:
            _put_binding(bindings, ehal_field, lox.get(legacy_key))


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
    _migrate_thermal_loxone(consumer, bindings)
    cid = _nonempty(consumer.get("id"))
    if cid:
        return expand_flex_bindings(bindings, cid)
    return bindings


FILTER_ENTITY_ID = "swimspa_filter"

FILTER_EHAL_FIELDS: tuple[str, ...] = (
    "get_filter_remaining_hours",
    "flex.swimspa_filter.sens_power_act",
    "flex.swimspa_filter.set_enable",
    "sens_filter_active",
    "get_filter_native_start_hour",
    "get_filter_native_duration_hours",
)


def filter_bindings_to_ehal_map(stored: dict | None) -> dict[str, str]:
    """Normalize ``swimspa_filter_bindings`` nest → EHAL field map for HITL / Live."""
    from ehal.flex_fields import (
        KIND_SENS_POWER_ACT,
        KIND_SET_ENABLE,
        expand_flex_bindings,
        flex_field,
    )

    raw = stored if isinstance(stored, dict) else {}
    out: dict[str, str] = {}
    existing = raw.get("ehal_bindings")
    if isinstance(existing, dict):
        for key, value in existing.items():
            _put_binding(out, str(key), value)
    _put_binding(out, "get_filter_remaining_hours", raw.get("loxone_target_hours_name"))
    inputs = raw.get("loxone_inputs") if isinstance(raw.get("loxone_inputs"), dict) else {}
    outputs = raw.get("loxone_outputs") if isinstance(raw.get("loxone_outputs"), dict) else {}
    flox = {}
    sched = raw.get("filter_schedule")
    if isinstance(sched, dict) and isinstance(sched.get("loxone"), dict):
        flox = sched["loxone"]
    _put_binding(
        out,
        flex_field(FILTER_ENTITY_ID, KIND_SENS_POWER_ACT),
        inputs.get("power_name"),
    )
    _put_binding(
        out,
        flex_field(FILTER_ENTITY_ID, KIND_SET_ENABLE),
        outputs.get("enable_name"),
    )
    _put_binding(out, "sens_filter_active", inputs.get("alternate_binary_power_name"))
    _put_binding(out, "get_filter_native_start_hour", flox.get("native_start_hour_name"))
    _put_binding(
        out, "get_filter_native_duration_hours", flox.get("native_duration_hours_name")
    )
    return expand_flex_bindings(out, FILTER_ENTITY_ID)


def ehal_map_to_filter_bindings(ehal_map: dict[str, str] | None) -> dict:
    """HITL save → ``swimspa_filter_bindings`` (EHAL-only persist)."""
    from ehal.flex_fields import expand_flex_bindings

    cleaned = expand_flex_bindings(
        {str(k): _nonempty(v) for k, v in (ehal_map or {}).items() if _nonempty(v)},
        FILTER_ENTITY_ID,
    )
    return {"ehal_bindings": cleaned} if cleaned else {}


def migrate_swimspa_filter_bindings(consumer: dict) -> bool:
    """Ensure ``swimspa_filter_bindings`` is EHAL-only with migrated addresses."""
    stored = consumer.get("swimspa_filter_bindings")
    if not isinstance(stored, dict) or not stored:
        return False
    migrated = filter_bindings_to_ehal_map(stored)
    cleaned = {"ehal_bindings": migrated} if migrated else {}
    if cleaned == stored:
        return False
    consumer["swimspa_filter_bindings"] = cleaned
    return True


def _strip_consumer_marker_nests(consumer: dict) -> bool:
    """Remove legacy Merker address nests after ehal_bindings is populated."""
    changed = False
    thermal = consumer.get("thermal_control")
    if isinstance(thermal, dict) and "loxone" in thermal:
        thermal = dict(thermal)
        thermal.pop("loxone", None)
        if thermal:
            consumer["thermal_control"] = thermal
        else:
            consumer.pop("thermal_control", None)
        changed = True
    inputs = consumer.get("loxone_inputs")
    if isinstance(inputs, dict):
        kept = {
            key: value
            for key, value in inputs.items()
            if str(key) not in _INPUT_MARKER_KEYS
        }
        if kept != inputs:
            if kept:
                consumer["loxone_inputs"] = kept
            else:
                consumer.pop("loxone_inputs", None)
            changed = True
    if isinstance(consumer.get("loxone_outputs"), dict):
        consumer.pop("loxone_outputs", None)
        changed = True
    sched = consumer.get("charging_schedule")
    if isinstance(sched, dict) and "loxone" in sched:
        sched = dict(sched)
        sched.pop("loxone", None)
        consumer["charging_schedule"] = sched
        changed = True
    fsched = consumer.get("filter_schedule")
    if isinstance(fsched, dict) and "loxone" in fsched:
        fsched = dict(fsched)
        fsched.pop("loxone", None)
        consumer["filter_schedule"] = fsched
        changed = True
    if "loxone_target_hours_name" in consumer:
        consumer.pop("loxone_target_hours_name", None)
        changed = True
    stored = consumer.get("swimspa_filter_bindings")
    if isinstance(stored, dict) and stored:
        ehal = stored.get("ehal_bindings")
        if isinstance(ehal, dict) and ehal and set(stored.keys()) != {"ehal_bindings"}:
            consumer["swimspa_filter_bindings"] = {"ehal_bindings": dict(ehal)}
            changed = True
        elif any(k != "ehal_bindings" for k in stored):
            mapped = filter_bindings_to_ehal_map(stored)
            consumer["swimspa_filter_bindings"] = (
                {"ehal_bindings": mapped} if mapped else {}
            )
            changed = True
    return changed


def strip_legacy_marker_nests(house_doc: dict | None) -> dict:
    """Drop legacy Merker nests from all consumers after migration."""
    house = copy.deepcopy(house_doc) if isinstance(house_doc, dict) else {}
    for profile in _profiles_iterable(house):
        consumers = profile.get("consumers")
        if not isinstance(consumers, list):
            continue
        for consumer in consumers:
            if isinstance(consumer, dict):
                _strip_consumer_marker_nests(consumer)
    return house


def _promote_ambient_to_plant(house: dict, plant_bindings: dict[str, str]) -> bool:
    if _nonempty(plant_bindings.get("sens_temperature_outside")):
        return False
    for profile in _profiles_iterable(house):
        consumers = profile.get("consumers")
        if not isinstance(consumers, list):
            continue
        for consumer in consumers:
            if not isinstance(consumer, dict):
                continue
            bindings = consumer.get("ehal_bindings")
            if isinstance(bindings, dict):
                ambient = _nonempty(bindings.get("sens_temperature_outside"))
                if ambient:
                    plant_bindings["sens_temperature_outside"] = ambient
                    return True
            thermal = consumer.get("thermal_control")
            if not isinstance(thermal, dict):
                continue
            lox = thermal.get("loxone")
            if isinstance(lox, dict):
                ambient = _nonempty(lox.get("ambient_temp_name"))
                if ambient:
                    plant_bindings["sens_temperature_outside"] = ambient
                    return True
    return False


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
    *,
    strip_legacy: bool = True,
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
    if _migrate_all_consumers(house):
        changed = True
    if _promote_ambient_to_plant(house, bindings):
        changed = True
    if bindings != (plant.get("ehal_bindings") or {}):
        plant["ehal_bindings"] = bindings
        changed = True
    if plant:
        house["plant"] = plant
    if _strip_entity_event_triggers(house):
        changed = True
    if strip_legacy:
        for profile in _profiles_iterable(house):
            for consumer in profile.get("consumers") or []:
                if isinstance(consumer, dict) and _strip_consumer_marker_nests(consumer):
                    changed = True
    return house, config, changed


def _consumer_has_legacy_markers(consumer: dict) -> bool:
    thermal = consumer.get("thermal_control")
    if isinstance(thermal, dict) and isinstance(thermal.get("loxone"), dict):
        return True
    inputs = consumer.get("loxone_inputs")
    if isinstance(inputs, dict) and any(k in _INPUT_MARKER_KEYS for k in inputs):
        return True
    if isinstance(consumer.get("loxone_outputs"), dict):
        return True
    sched = consumer.get("charging_schedule")
    if isinstance(sched, dict) and isinstance(sched.get("loxone"), dict):
        return True
    fsched = consumer.get("filter_schedule")
    if isinstance(fsched, dict) and isinstance(fsched.get("loxone"), dict):
        return True
    if consumer.get("loxone_target_hours_name"):
        return True
    stored = consumer.get("swimspa_filter_bindings")
    if isinstance(stored, dict) and any(k != "ehal_bindings" for k in stored):
        return True
    return False


def _migrate_all_consumers(house: dict) -> bool:
    changed = False
    for profile in _profiles_iterable(house):
        consumers = profile.get("consumers")
        if not isinstance(consumers, list):
            continue
        for consumer in consumers:
            if not isinstance(consumer, dict):
                continue
            migrated = migrate_consumer_legacy_to_ehal_bindings(consumer)
            existing = consumer.get("ehal_bindings")
            existing_map = (
                {str(k): _nonempty(v) for k, v in existing.items() if _nonempty(v)}
                if isinstance(existing, dict)
                else {}
            )
            if migrated != existing_map:
                consumer["ehal_bindings"] = migrated
                changed = True
            if migrate_swimspa_filter_bindings(consumer):
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
