"""Filter (pool pump) EHAL binding helpers (split from ehal_bindings)."""
from __future__ import annotations

from house_config.ehal_bindings_util import _nonempty, _put_binding

FILTER_ENTITY_ID = "pool_filter"
FILTER_CONSUMER_TYPE = "thermal_rc"


def filter_ehal_fields_for_consumer(cid: str) -> tuple[str, ...]:
    """HITL / Live filter field catalog with slug-aware power + enable."""
    from ehal.flex_fields import (
        KIND_SENS_POWER_ACT,
        KIND_SET_ENABLE,
        consumer_storage_field,
    )

    slug = str(cid or "").strip() or FILTER_ENTITY_ID
    return (
        "get_filter_remaining_hours",
        consumer_storage_field(slug, FILTER_CONSUMER_TYPE, KIND_SENS_POWER_ACT),
        consumer_storage_field(slug, FILTER_CONSUMER_TYPE, KIND_SET_ENABLE),
        "sens_filter_active",
        "get_filter_native_start_hour",
        "get_filter_native_duration_hours",
    )


FILTER_EHAL_FIELDS: tuple[str, ...] = filter_ehal_fields_for_consumer(FILTER_ENTITY_ID)


def filter_bindings_to_ehal_map(stored: dict | None) -> dict[str, str]:
    """Normalize legacy ``swimspa_filter_bindings`` nest → EHAL field map (pool_filter keys)."""
    from ehal.flex_fields import (
        KIND_SENS_POWER_ACT,
        KIND_SET_ENABLE,
        canonicalize_consumer_bindings,
        consumer_storage_field,
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
    # Prefer already-migrated pool_filter keys; fall back to swimspa bridge / flex.
    power_key = consumer_storage_field(
        FILTER_ENTITY_ID, FILTER_CONSUMER_TYPE, KIND_SENS_POWER_ACT
    )
    enable_key = consumer_storage_field(
        FILTER_ENTITY_ID, FILTER_CONSUMER_TYPE, KIND_SET_ENABLE
    )
    power = (
        inputs.get("power_name")
        or out.get(power_key)
        or out.get(flex_field("swimspa_filter", KIND_SENS_POWER_ACT))
        or out.get(flex_field(FILTER_ENTITY_ID, KIND_SENS_POWER_ACT))
    )
    enable = (
        outputs.get("enable_name")
        or out.get(enable_key)
        or out.get(flex_field("swimspa_filter", KIND_SET_ENABLE))
        or out.get(flex_field(FILTER_ENTITY_ID, KIND_SET_ENABLE))
    )
    out.pop(flex_field("swimspa_filter", KIND_SENS_POWER_ACT), None)
    out.pop(flex_field("swimspa_filter", KIND_SET_ENABLE), None)
    out.pop(flex_field(FILTER_ENTITY_ID, KIND_SENS_POWER_ACT), None)
    out.pop(flex_field(FILTER_ENTITY_ID, KIND_SET_ENABLE), None)
    _put_binding(out, power_key, power)
    _put_binding(out, enable_key, enable)
    _put_binding(out, "sens_filter_active", inputs.get("alternate_binary_power_name"))
    _put_binding(out, "get_filter_native_start_hour", flox.get("native_start_hour_name"))
    _put_binding(
        out, "get_filter_native_duration_hours", flox.get("native_duration_hours_name")
    )
    return canonicalize_consumer_bindings(
        out, FILTER_ENTITY_ID, FILTER_CONSUMER_TYPE
    )


def ehal_map_to_filter_bindings(ehal_map: dict[str, str] | None) -> dict:
    """Normalize HITL map → ``ehal_bindings`` dict for ``pool_filter``."""
    from ehal.flex_fields import canonicalize_consumer_bindings

    cleaned = canonicalize_consumer_bindings(
        {str(k): _nonempty(v) for k, v in (ehal_map or {}).items() if _nonempty(v)},
        FILTER_ENTITY_ID,
        FILTER_CONSUMER_TYPE,
    )
    return cleaned


def assemble_filter_bindings(values: dict[str, str]) -> dict:
    """Build ``ehal_bindings`` map for ``pool_filter`` from edited marker addresses."""
    from ehal.flex_fields import (
        KIND_SENS_POWER_ACT,
        KIND_SET_ENABLE,
        consumer_storage_field,
    )

    ehal_map: dict[str, str] = {}
    target_hours = str(values.get("loxone_target_hours_name") or "").strip()
    if target_hours:
        ehal_map["get_filter_remaining_hours"] = target_hours
    power_name = str(values.get("power_name") or "").strip()
    if power_name:
        ehal_map[
            consumer_storage_field(
                FILTER_ENTITY_ID, FILTER_CONSUMER_TYPE, KIND_SENS_POWER_ACT
            )
        ] = power_name
    alt_power = str(values.get("alternate_binary_power_name") or "").strip()
    if alt_power:
        ehal_map["sens_filter_active"] = alt_power
    enable_name = str(values.get("enable_name") or "").strip()
    if enable_name:
        ehal_map[
            consumer_storage_field(
                FILTER_ENTITY_ID, FILTER_CONSUMER_TYPE, KIND_SET_ENABLE
            )
        ] = enable_name
    native_start = str(values.get("native_start_hour_name") or "").strip()
    if native_start:
        ehal_map["get_filter_native_start_hour"] = native_start
    native_dur = str(values.get("native_duration_hours_name") or "").strip()
    if native_dur:
        ehal_map["get_filter_native_duration_hours"] = native_dur
    return {"ehal_bindings": ehal_map_to_filter_bindings(ehal_map)}


def migrate_swimspa_filter_bindings(consumer: dict) -> bool:
    """Legacy no-op: nests are lifted onto ``pool_filter`` by ``promote_pool_filter_milp``."""
    stored = consumer.get("swimspa_filter_bindings")
    if not isinstance(stored, dict) or not stored:
        return False
    migrated = filter_bindings_to_ehal_map(stored)
    cleaned = {"ehal_bindings": migrated} if migrated else {}
    if cleaned == stored:
        return False
    consumer["swimspa_filter_bindings"] = cleaned
    return True
