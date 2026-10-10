"""Resolve Merker addresses from ``ehal_bindings`` (§C / Pattern B keys only).

Read and write fields: Merker name if set, else qualified EHAL ID when the binding
key is present (Q8 activation flag; empty Merker is allowed for Loxone push-only).
"""
from __future__ import annotations


def _first_nonempty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def ehal_bindings(consumer: dict) -> dict:
    bindings = consumer.get("ehal_bindings")
    return bindings if isinstance(bindings, dict) else {}


def _consumer_pilot_id(consumer: dict, ehal_field: str) -> str:
    from ehal.push_signals import pilot_id

    cid = str(consumer.get("id") or "").strip()
    ctype = str(consumer.get("type") or "")
    return str(pilot_id("consumer", cid, ehal_field, ctype) or "").strip()


def _resolve_binding_key(consumer: dict, ehal_field: str) -> str:
    """Merker if set; else qualified ID when ``ehal_field`` key is present."""
    from ehal.qualified_ids import field_kind, parse_qualified_id

    bindings = ehal_bindings(consumer)
    merker = _first_nonempty(bindings.get(ehal_field))
    if merker:
        return merker
    for key, value in bindings.items():
        if field_kind(str(key)) != ehal_field:
            continue
        parsed = parse_qualified_id(str(key))
        if parsed is None or parsed.is_plant_bare:
            continue
        text = str(value or "").strip()
        return text or str(key)
    if ehal_field not in bindings:
        return ""
    return _consumer_pilot_id(consumer, ehal_field)


def resolve_lox_marker(consumer: dict, ehal_field: str) -> str:
    """Read address: Merker or, if key present and empty, qualified EHAL ID."""
    from ehal.loxone_push_source import is_pushable_kind
    from ehal.qualified_ids import field_kind, parse_qualified_id

    bindings = ehal_bindings(consumer)
    merker = _first_nonempty(bindings.get(ehal_field))
    if merker:
        return merker
    # Prefer a stored qualified key (correct namespace even if MILP shape lost ``type``).
    for key, value in bindings.items():
        if field_kind(str(key)) != ehal_field:
            continue
        parsed = parse_qualified_id(str(key))
        if parsed is None or parsed.is_plant_bare:
            continue
        text = str(value or "").strip()
        return text or str(key)
    if ehal_field not in bindings:
        return ""
    if not is_pushable_kind(ehal_field):
        return ""
    return _consumer_pilot_id(consumer, ehal_field)


def resolve_output_marker(consumer: dict, ehal_field: str) -> str:
    """Write address: Merker or qualified EHAL ID when the binding key is present."""
    return _resolve_binding_key(consumer, ehal_field)


def marker_flex_power(consumer: dict) -> str:
    """Consumer Messwert power from ``ehal_bindings`` (Pattern B)."""
    from ehal.flex_fields import KIND_SENS_POWER_ACT, binding_address, flex_field

    cid = str(consumer.get("id") or "").strip()
    if not cid:
        return ""
    bindings = ehal_bindings(consumer)
    merker = binding_address(bindings, cid, KIND_SENS_POWER_ACT)
    if merker:
        return merker
    key = flex_field(cid, KIND_SENS_POWER_ACT)
    if key not in bindings and KIND_SENS_POWER_ACT not in bindings:
        return ""
    return _consumer_pilot_id(consumer, KIND_SENS_POWER_ACT)


def marker_sens_evcs_active_power(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_evcs_active_power")


def marker_get_filter_remaining_hours(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_filter_remaining_hours")


def marker_sens_filter_active(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_filter_active")


def marker_flex_enable(consumer: dict) -> str:
    """Consumer Freigabe: Merker or qid when any ``*.set_enable`` key is present."""
    from ehal.flex_fields import KIND_SET_ENABLE, binding_address, flex_field
    from ehal.qualified_ids import field_kind

    cid = str(consumer.get("id") or "").strip()
    if not cid:
        return ""
    bindings = ehal_bindings(consumer)
    merker = binding_address(bindings, cid, KIND_SET_ENABLE)
    if merker:
        return merker
    qid = _consumer_pilot_id(consumer, KIND_SET_ENABLE)
    for key, value in bindings.items():
        if field_kind(str(key)) != KIND_SET_ENABLE:
            continue
        text = str(value or "").strip()
        return text or qid
    if flex_field(cid, KIND_SET_ENABLE) in bindings or KIND_SET_ENABLE in bindings:
        return qid
    return ""


def marker_sens_consumer_active(consumer: dict) -> str:
    """Digital Gerät-läuft Merker (2.7.p) from Pattern B bindings."""
    from ehal.flex_fields import (
        KIND_SENS_CONSUMER_ACTIVE,
        binding_address,
        flex_field,
    )

    cid = str(consumer.get("id") or "").strip()
    if not cid:
        return ""
    bindings = ehal_bindings(consumer)
    merker = binding_address(bindings, cid, KIND_SENS_CONSUMER_ACTIVE)
    if merker:
        return merker
    key = flex_field(cid, KIND_SENS_CONSUMER_ACTIVE)
    if key not in bindings and KIND_SENS_CONSUMER_ACTIVE not in bindings:
        # Legacy alternate binary used as run indicator for manuals.
        return _first_nonempty(bindings.get("flex.alternate_binary_power_name"))
    return _consumer_pilot_id(consumer, KIND_SENS_CONSUMER_ACTIVE)


def marker_sens_evcs_connected(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_evcs_connected")


def marker_sens_evcs_soc_act(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_evcs_soc_act")


def marker_sens_evcs_bat_capacity(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_evcs_bat_capacity")


def marker_get_evcs_nominal_current(consumer: dict) -> str:
    return _first_nonempty(
        resolve_lox_marker(consumer, "get_evcs_nominal_current"),
        resolve_lox_marker(consumer, "sens_evcs_nominal_current"),
    )


def marker_get_evcs_ready_by_time(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_evcs_ready_by_time")


def marker_set_evcs_max_current(consumer: dict) -> str:
    """EV current setpoint: Merker or qid when binding key is present (Q8)."""
    for field in ("set_evcs_max_current", "set_evcs_current"):
        resolved = resolve_output_marker(consumer, field)
        if resolved:
            return resolved
    return ""


def marker_charge_immediate(consumer: dict) -> str:
    """Read-only Nutzerwunsch ``Sofort laden`` sensor (never a write role)."""
    return resolve_lox_marker(consumer, "charge_immediate_name")


def marker_set_evcs_mode(consumer: dict) -> str:
    return resolve_output_marker(consumer, "set_evcs_mode")


def marker_get_evcs_limit_soc(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_evcs_limit_soc")


def marker_get_evcs_soc_min_immediate(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_evcs_soc_min_immediate")


def marker_get_filter_native_start_hour(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_filter_native_start_hour")


def marker_get_filter_native_duration_hours(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_filter_native_duration_hours")


def marker_sens_temperature_water(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_temperature_water")


def marker_sens_temperature_heat_storage(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_temperature_heat_storage")


def marker_sens_temperature_heat_storage_low(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_temperature_heat_storage_low")


def marker_get_temperature_water_setpoint(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_temperature_water_setpoint")


def marker_get_temperature_tolerance_c(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "get_temperature_tolerance_c")


def marker_sens_heating_active(consumer: dict) -> str:
    return resolve_lox_marker(consumer, "sens_heating_active")


def marker_sens_temperature_outside(
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> str:
    """Außentemperatur: plant ``sens_temperature_outside`` only (no consumer/legacy dual-read)."""
    from house_config.ehal_bindings import resolve_plant_binding

    return resolve_plant_binding(house_doc, "sens_temperature_outside", config_doc)


def marker_sens_absent_mode(
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> str:
    """Abwesenheitsmodus: plant ``sens_absent_mode`` only."""
    from house_config.ehal_bindings import resolve_plant_binding

    return resolve_plant_binding(house_doc, "sens_absent_mode", config_doc)


def marker_get_grid_export_power_limit(
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> str:
    """Inbound export cap: plant ``get_grid_export_power_limit`` only (kW on Loxone)."""
    from house_config.ehal_bindings import resolve_plant_binding

    return resolve_plant_binding(house_doc, "get_grid_export_power_limit", config_doc)


def marker_get_ess_soc_min(
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> str:
    """Plant ``get_ess_soc_min`` Merker (%)."""
    from house_config.ehal_bindings import resolve_plant_binding

    return resolve_plant_binding(house_doc, "get_ess_soc_min", config_doc)


def marker_get_ess_soc_max(
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> str:
    """Plant ``get_ess_soc_max`` Merker (%)."""
    from house_config.ehal_bindings import resolve_plant_binding

    return resolve_plant_binding(house_doc, "get_ess_soc_max", config_doc)


def marker_get_ess_max_charge_power(
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> str:
    """Plant ``get_ess_max_charge_power`` Merker (kW on Loxone → EHAL W)."""
    from house_config.ehal_bindings import resolve_plant_binding

    return resolve_plant_binding(house_doc, "get_ess_max_charge_power", config_doc)


def marker_get_ess_max_discharge_power(
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> str:
    """Plant ``get_ess_max_discharge_power`` Merker (kW on Loxone → EHAL W)."""
    from house_config.ehal_bindings import resolve_plant_binding

    return resolve_plant_binding(house_doc, "get_ess_max_discharge_power", config_doc)


def resolve_get_evcs_limit_soc(consumer: dict) -> float:
    """Limit SoC %: optional ``get_evcs_limit_soc`` Merker, else profile percent."""
    from integrations import loxone_client

    io_name = marker_get_evcs_limit_soc(consumer)
    if io_name:
        raw = loxone_client.fetch_loxone_generic_value(io_name)
        if raw is None:
            raise ValueError(
                f"Verbraucher '{consumer.get('id', '?')}': "
                f"get_evcs_limit_soc Merker '{io_name}' nicht lesbar."
            )
        return float(raw)
    sched = consumer.get("charging_schedule") or {}
    return float(sched.get("target_soc_percent", 100.0) or 100.0)


def resolve_get_evcs_soc_min_immediate(consumer: dict) -> float | None:
    """ASAP min SoC %; None = inactive. Clamped to Limit-SOC when active."""
    from integrations import loxone_client

    io_name = marker_get_evcs_soc_min_immediate(consumer)
    if not io_name:
        return None
    raw = loxone_client.fetch_loxone_generic_value(io_name)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0.0:
        return None
    limit_soc = resolve_get_evcs_limit_soc(consumer)
    return min(value, float(limit_soc))
