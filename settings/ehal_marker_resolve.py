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


def marker_sens_evcs_nominal_current(consumer: dict) -> str:
    return resolve_lox_marker(
        consumer, "sens_evcs_nominal_current", legacy="nominal_power_kw_name"
    )


def marker_get_evcs_ready_by_time(consumer: dict) -> str:
    return resolve_lox_marker(
        consumer, "get_evcs_ready_by_time", legacy="ready_by_time_name"
    )


def marker_set_evcs_max_current(consumer: dict) -> str:
    return resolve_output_marker(
        consumer, "set_evcs_max_current", legacy="set_evcs_max_current"
    )


def marker_set_evcs_current(consumer: dict) -> str:
    return resolve_output_marker(
        consumer, "set_evcs_current", legacy="power_setpoint_name"
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


def resolve_get_evcs_limit_soc(consumer: dict) -> float:
    """Limit SoC %: optional ``get_evcs_limit_soc`` Merker, else profile percent."""
    from integrations import loxone_client

    io_name = _first_nonempty(
        ehal_bindings(consumer).get("get_evcs_limit_soc"),
        charging_loxone(consumer).get("get_evcs_limit_soc"),
    )
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
