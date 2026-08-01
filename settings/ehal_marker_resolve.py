"""Dual-read EHAL §C names vs legacy Loxone ``*_name`` keys during 2.4.j/k."""
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


def charging_loxone(consumer: dict) -> dict:
    sched = consumer.get("charging_schedule") or {}
    return sched.get("loxone") or {}


def loxone_outputs(consumer: dict) -> dict:
    return consumer.get("loxone_outputs") or {}


def resolve_lox_marker(consumer: dict, ehal_field: str, *, legacy: str) -> str:
    """Prefer ``ehal_bindings``, then EHAL key on loxone dict, else legacy ``*_name``."""
    lox = charging_loxone(consumer)
    return _first_nonempty(
        ehal_bindings(consumer).get(ehal_field),
        lox.get(ehal_field),
        lox.get(legacy),
    )


def resolve_output_marker(consumer: dict, ehal_field: str, *, legacy: str) -> str:
    """Prefer ``ehal_bindings``, then loxone_outputs EHAL/legacy keys."""
    outputs = loxone_outputs(consumer)
    return _first_nonempty(
        ehal_bindings(consumer).get(ehal_field),
        outputs.get(ehal_field),
        outputs.get(legacy),
    )


def marker_sens_evcs_active_power(consumer: dict) -> str:
    """EV wallbox power: bindings first, else ``loxone_inputs.power_name``."""
    inputs = consumer.get("loxone_inputs") or {}
    return _first_nonempty(
        ehal_bindings(consumer).get("sens_evcs_active_power"),
        inputs.get("sens_evcs_active_power"),
        inputs.get("power_name"),
    )


def marker_flex_power(consumer: dict) -> str:
    """Consumer Messwert power: Pattern B / legacy ``flex.power_name``, else inputs."""
    from ehal.flex_fields import KIND_SENS_POWER_ACT, binding_address

    inputs = consumer.get("loxone_inputs") or {}
    cid = str(consumer.get("id") or "").strip()
    return _first_nonempty(
        binding_address(ehal_bindings(consumer), cid, KIND_SENS_POWER_ACT)
        if cid
        else "",
        ehal_bindings(consumer).get("flex.power_name"),
        inputs.get("flex.power_name"),
        inputs.get("power_name"),
    )


def marker_flex_enable(consumer: dict) -> str:
    """Consumer Freigabe: Pattern B / legacy ``flex.enable_name``, else outputs."""
    from ehal.flex_fields import KIND_SET_ENABLE, binding_address

    outputs = loxone_outputs(consumer)
    cid = str(consumer.get("id") or "").strip()
    return _first_nonempty(
        binding_address(ehal_bindings(consumer), cid, KIND_SET_ENABLE) if cid else "",
        ehal_bindings(consumer).get("flex.enable_name"),
        outputs.get("flex.enable_name"),
        outputs.get("enable_name"),
    )


def marker_flex_power_setpoint(consumer: dict) -> str:
    """Consumer Sollwert: Pattern B / legacy ``flex.power_setpoint_name``, else outputs."""
    from ehal.flex_fields import KIND_SET_POWER_SETPOINT, binding_address

    outputs = loxone_outputs(consumer)
    cid = str(consumer.get("id") or "").strip()
    return _first_nonempty(
        binding_address(ehal_bindings(consumer), cid, KIND_SET_POWER_SETPOINT)
        if cid
        else "",
        ehal_bindings(consumer).get("flex.power_setpoint_name"),
        outputs.get("flex.power_setpoint_name"),
        outputs.get("power_setpoint_name"),
    )


def marker_sens_evcs_connected(consumer: dict) -> str:
    return resolve_lox_marker(
        consumer, "sens_evcs_connected", legacy="plugged_in_name"
    )


def marker_sens_evcs_soc_act(consumer: dict) -> str:
    return resolve_lox_marker(
        consumer, "sens_evcs_soc_act", legacy="actual_soc_name"
    )


def marker_sens_evcs_bat_capacity(consumer: dict) -> str:
    return resolve_lox_marker(
        consumer, "sens_evcs_bat_capacity", legacy="battery_capacity_kwh_name"
    )


def marker_get_evcs_nominal_current(consumer: dict) -> str:
    """Nominal current Merker; dual-read legacy ``sens_evcs_nominal_current`` / kW name."""
    lox = charging_loxone(consumer)
    return _first_nonempty(
        ehal_bindings(consumer).get("get_evcs_nominal_current"),
        ehal_bindings(consumer).get("sens_evcs_nominal_current"),
        lox.get("get_evcs_nominal_current"),
        lox.get("sens_evcs_nominal_current"),
        lox.get("nominal_power_kw_name"),
    )


def marker_get_evcs_ready_by_time(consumer: dict) -> str:
    return resolve_lox_marker(
        consumer, "get_evcs_ready_by_time", legacy="ready_by_time_name"
    )


def marker_set_evcs_max_current(consumer: dict) -> str:
    """EV current setpoint Merker; dual-read legacy ``set_evcs_current`` / ``power_setpoint_name``."""
    outputs = loxone_outputs(consumer)
    return _first_nonempty(
        ehal_bindings(consumer).get("set_evcs_max_current"),
        ehal_bindings(consumer).get("set_evcs_current"),
        outputs.get("set_evcs_max_current"),
        outputs.get("set_evcs_current"),
        outputs.get("power_setpoint_name"),
    )


def marker_pv_follow(consumer: dict) -> str:
    return _first_nonempty(
        ehal_bindings(consumer).get("pv_follow_name"),
        loxone_outputs(consumer).get("pv_follow_name"),
    )


def marker_charge_immediate(consumer: dict) -> str:
    return _first_nonempty(
        ehal_bindings(consumer).get("charge_immediate_name"),
        charging_loxone(consumer).get("charge_immediate_name"),
    )


def marker_set_evcs_mode(consumer: dict) -> str:
    """Optional dedicated mode Merker on bindings, outputs, or charging_schedule.loxone."""
    return _first_nonempty(
        ehal_bindings(consumer).get("set_evcs_mode"),
        loxone_outputs(consumer).get("set_evcs_mode"),
        charging_loxone(consumer).get("set_evcs_mode"),
    )


def marker_get_evcs_limit_soc(consumer: dict) -> str:
    return _first_nonempty(
        ehal_bindings(consumer).get("get_evcs_limit_soc"),
        charging_loxone(consumer).get("get_evcs_limit_soc"),
    )


def marker_get_filter_remaining_hours(consumer: dict) -> str:
    """Filter Sollstunden Merker; prefer EHAL role, else legacy ``loxone_target_hours_name``."""
    return _first_nonempty(
        ehal_bindings(consumer).get("get_filter_remaining_hours"),
        consumer.get("loxone_target_hours_name"),
    )


def marker_sens_filter_active(consumer: dict) -> str:
    """Binary filter-running Merker; dual-read alternate Homie input."""
    inputs = consumer.get("loxone_inputs") or {}
    return _first_nonempty(
        ehal_bindings(consumer).get("sens_filter_active"),
        inputs.get("sens_filter_active"),
        inputs.get("alternate_binary_power_name"),
    )


def marker_get_filter_native_start_hour(consumer: dict) -> str:
    flox = (consumer.get("filter_schedule") or {}).get("loxone") or {}
    return _first_nonempty(
        ehal_bindings(consumer).get("get_filter_native_start_hour"),
        flox.get("get_filter_native_start_hour"),
        flox.get("native_start_hour_name"),
    )


def marker_get_filter_native_duration_hours(consumer: dict) -> str:
    flox = (consumer.get("filter_schedule") or {}).get("loxone") or {}
    return _first_nonempty(
        ehal_bindings(consumer).get("get_filter_native_duration_hours"),
        flox.get("get_filter_native_duration_hours"),
        flox.get("native_duration_hours_name"),
    )


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
