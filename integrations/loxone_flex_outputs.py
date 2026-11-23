"""Flexible consumer output values (Merker → value) for the Loxone/EHAL write path.

Pure value computation without publishing. Split from ``integrations.loxone_writes``
(2.8 quality gate); that module stays the import facade and re-exports these names.
"""
from __future__ import annotations

import logging

from settings.ehal_marker_resolve import (
    marker_flex_enable,
    marker_set_evcs_max_current,
    marker_set_evcs_mode,
    marker_set_sg_ready_state,
    marker_set_store_target,
)
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

# Same logger name as before the split, so log filters and captures stay unchanged.
logger = logging.getLogger("integrations.loxone_writes")


def flex_consumer_enable_value(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
) -> int | None:
    """Freigabe 0/1 für einen flexiblen Verbraucher (None wenn kein enable Merker)."""
    if not marker_flex_enable(consumer):
        return None

    cid = consumer["id"]
    power_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    return 1 if power_kw > 1e-3 else 0


def _effective_consumer_power_kw(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    cid: str,
) -> float:
    power_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
    ctx = charging_contexts.get(cid)
    if ctx is not None and not ctx.get("active", True):
        return 0.0
    if ctx is not None and ctx.get("anticipated") and not ctx.get("plugged_in"):
        return 0.0
    return power_kw


def flex_consumer_power_setpoint_kw(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> float | None:
    """kW-Sollwert aus MILP (None wenn kein set_evcs_max_current / power_setpoint)."""
    from optimizer.consumer_power import loxone_control_outputs

    if not marker_set_evcs_max_current(consumer):
        return None

    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    pv_follow = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    setpoint_kw, _ = loxone_control_outputs(consumer, planned_kw, pv_follow)
    return setpoint_kw


def flex_consumer_setpoint_amps(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> float | None:
    """set_evcs_max_current (A) from planned kW; None wenn kein Current-Merker."""
    setpoint_kw = flex_consumer_power_setpoint_kw(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    if setpoint_kw is None:
        return None
    voltage_v, phases = ev_nominal_power_conversion(consumer)
    return round(kw_to_ampere(setpoint_kw, voltage_v=voltage_v, phases=phases), 3)


def _skip_flexible_consumer_output(
    consumer: dict,
    charging_contexts: dict[str, dict],
) -> bool:
    ctx = charging_contexts.get(consumer["id"]) or {}
    return bool(ctx.get("skip_loxone_output"))


_EVCS_MODE_VALUES: dict[str, float] = {"off": 0.0, "pv": 1.0, "now": 2.0}


def _append_evcs_mode_writes(
    values: dict[str, float],
    consumer: dict,
    *,
    mode: str | None,
) -> None:
    """Write the canonical ``set_evcs_mode`` Merker (off=0, pv=1, now=2)."""
    mode_name = marker_set_evcs_mode(consumer)
    if not mode_name:
        return
    values[mode_name] = _EVCS_MODE_VALUES.get(str(mode or "").strip().lower(), 0.0)


def _immediate_skip_output_values(consumer: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    _append_evcs_mode_writes(values, consumer, mode="now")
    if values:
        logger.info(
            "Flex consumer %s -> Sofort laden: set_evcs_mode=now "
            "(kein Lade-Sollstrom von Earnie).",
            consumer["name"],
        )
    else:
        logger.info(
            "Flex consumer %s -> keine Steuerung (Sofort laden aktiv, Loxone regelt).",
            consumer["name"],
        )
    return values


def _evcs_current_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None,
    current_name: str,
) -> dict[str, float]:
    from optimizer.consumer_power import loxone_control_outputs, set_evcs_mode_for_plan

    amps = flex_consumer_setpoint_amps(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    if amps is None:
        return {}
    values = {str(current_name): float(amps)}
    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(
        consumer, consumer_powers, charging_contexts, cid
    )
    plan_pv = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    _, pv_out = loxone_control_outputs(consumer, planned_kw, plan_pv)
    mode = set_evcs_mode_for_plan(
        pv_follow=int(pv_out),
        immediate=False,
        charging=float(amps) > 1e-6,
    )
    _append_evcs_mode_writes(values, consumer, mode=mode)
    setpoint_kw = flex_consumer_power_setpoint_kw(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    logger.info(
        "Flex consumer %s -> Soll=%.2f A (%.2f kW), mode=%s "
        "(geplant %.2f kW, Loxone: %s)",
        consumer["name"],
        amps,
        setpoint_kw or 0.0,
        mode,
        max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0)),
        current_name,
    )
    return values


def _enable_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    enable_name: str,
) -> dict[str, float]:
    enabled = flex_consumer_enable_value(consumer, consumer_powers, charging_contexts)
    if enabled is None:
        return {}
    power_kw = max(0.0, float(consumer_powers.get(consumer["id"], 0.0) or 0.0))
    logger.info(
        "Flex consumer %s -> Freigabe=%s (optimiert %.2f kW, Loxone: %s)",
        consumer["name"],
        enabled,
        power_kw,
        enable_name,
    )
    return {str(enable_name): float(enabled)}


def _sg_ready_state_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    *,
    forced: bool = False,
) -> dict[str, float]:
    """Heat pump operating state (HeatControl P2): 3 where the plan runs it, else 2.

    ``forced`` (HeatControl P5): the plan runs it on a negative price or on surplus that
    would be curtailed, the state is 4. Sent next to ``set_enable`` when the key is mapped;
    it never replaces it.
    """
    from ehal.heat_fields import sg_ready_state_for_plan

    state_name = marker_set_sg_ready_state(consumer)
    if not state_name:
        return {}
    power_kw = _effective_consumer_power_kw(
        consumer, consumer_powers, charging_contexts, consumer["id"]
    )
    state = sg_ready_state_for_plan(power_kw > 1e-3, forced=forced)
    logger.info(
        "Flex consumer %s -> SG-Ready-Zustand=%s (optimiert %.2f kW, Loxone: %s)",
        consumer["name"],
        state,
        power_kw,
        state_name,
    )
    return {str(state_name): float(state)}


def _store_target_output_values(
    consumer: dict,
    heat_storage_targets: dict[str, float] | None,
) -> dict[str, float]:
    """Store charge target (HeatControl P3): the plan's target, 0 = no target.

    ``None``: no plan was made in this call (e.g. the watchdog's snapshot); nothing is
    written then. A heat pump without a computed target gets 0 (no target).
    """
    if heat_storage_targets is None:
        return {}
    name = marker_set_store_target(consumer)
    if not name:
        return {}
    value = float(heat_storage_targets.get(str(consumer["id"]), 0.0) or 0.0)
    logger.info(
        "Flex consumer %s -> Speicher-Ladeziel=%.1f °C (0 = kein Ziel, Loxone: %s)",
        consumer["name"],
        value,
        name,
    )
    return {str(name): value}


def _flexible_consumer_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
    heat_storage_targets: dict[str, float] | None = None,
    heat_forced_charge: frozenset[str] | None = None,
) -> dict[str, float]:
    """Berechnet Loxone-Merker → Wert für einen flexiblen Verbraucher (ohne HTTP)."""
    if _skip_flexible_consumer_output(consumer, charging_contexts):
        return _immediate_skip_output_values(consumer)

    current_name = marker_set_evcs_max_current(consumer)
    enable_name = marker_flex_enable(consumer)
    if current_name:
        return _evcs_current_output_values(
            consumer,
            consumer_powers,
            charging_contexts,
            consumer_pv_follow,
            current_name,
        )

    values: dict[str, float] = {}
    if enable_name:
        values.update(
            _enable_output_values(
                consumer, consumer_powers, charging_contexts, enable_name
            )
        )
    values.update(
        _sg_ready_state_output_values(
            consumer,
            consumer_powers,
            charging_contexts,
            forced=str(consumer["id"]) in (heat_forced_charge or ()),
        )
    )
    values.update(_store_target_output_values(consumer, heat_storage_targets))
    return values
