"""Live-cycle hooks for 2.7.g powerstation reserves."""
from __future__ import annotations

import logging
from typing import Any

import config
from house_config.powerstation import MODE_RESERVE
from optimizer.powerstation_reserve import (
    advance_reserve_after_slot,
    collect_active_reserves,
    detect_trigger_from_power,
    physical_reserves,
    prepare_battery_params_for_reserves,
    virtual_asap_charge_kwh,
)
from runtime_store.powerstation_reserves import set_trigger

logger = logging.getLogger(__name__)


def _planning_powerstations() -> list[dict]:
    try:
        resolved = config.get_resolved_runtime_settings()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(resolved, dict):
        return []
    value = resolved.get("_planning_powerstations")
    return list(value) if isinstance(value, list) else []


def _reserve_appliances() -> list[dict]:
    from house_config.powerstation import MODE_RESERVE

    try:
        appliances = config.get_appliances()
    except Exception:  # noqa: BLE001
        logger.warning("powerstation_live: get_appliances failed")
        return []
    return [
        a for a in appliances if str(a.get("mode") or "") == MODE_RESERVE
    ]


def load_active_reserves() -> list[dict[str, Any]]:
    return collect_active_reserves(
        appliances=_reserve_appliances(),
        powerstations=_planning_powerstations(),
    )


def apply_reserves_to_battery_params(
    battery_params: dict | list[dict],
    reserves: list[dict[str, Any]] | None = None,
) -> dict | list[dict]:
    active = reserves if reserves is not None else load_active_reserves()
    return prepare_battery_params_for_reserves(battery_params, active)


def sync_triggers_from_telemetry(
    telemetry: dict[str, Any] | None,
    reserves: list[dict[str, Any]],
) -> None:
    """Threshold crossing on flex sens_power_act or manual trigger flag."""
    if not isinstance(telemetry, dict):
        return
    for reserve in reserves:
        ps_id = str(reserve.get("powerstation_id") or "")
        if not ps_id:
            continue
        appliance_ids = [
            str(cid).strip()
            for cid in (reserve.get("appliance_ids") or [])
            if str(cid or "").strip()
        ]
        if not appliance_ids:
            singular = str(reserve.get("appliance_id") or "").strip()
            if singular:
                appliance_ids = [singular]
        triggered = False
        for appliance_id in appliance_ids:
            field = f"flex.{appliance_id}.sens_power_act"
            power = telemetry.get(field)
            if detect_trigger_from_power(
                float(power) if power is not None else None
            ):
                triggered = True
                break
        if not triggered:
            # Physical pack out power as free meter (2.7.g bonus).
            power = telemetry.get(f"ess.{ps_id}.sens_ess_power")
            triggered = detect_trigger_from_power(
                float(power) if power is not None else None
            )
        if triggered:
            set_trigger(ps_id, active=True)


def advance_virtual_reserves_from_plan(
    *,
    battery_plan_kw: float,
    dt_h: float,
    reserves: list[dict[str, Any]],
) -> None:
    """Attribute house charge/discharge to virtual carve-outs after a slot plan."""
    asap_total = virtual_asap_charge_kwh(reserves)
    charge_kw = max(0.0, float(battery_plan_kw))
    discharge_kw = max(0.0, -float(battery_plan_kw))
    charge_kwh = charge_kw * dt_h
    discharge_kwh = discharge_kw * dt_h

    virtual = [r for r in reserves if r.get("backing") == "virtual"]
    if not virtual:
        return

    # Equal-share ASAP charge attribution (priority deferred to 2.+1).
    needing = [r for r in virtual if float(r.get("asap_charge_kwh") or 0.0) > 1e-9]
    if needing and charge_kwh > 1e-9:
        share = charge_kwh / len(needing)
        for reserve in needing:
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                charged_kwh=share,
            )

    discharging = [
        r for r in virtual if r.get("state") == "discharging" or r.get("trigger_active")
    ]
    if discharging and discharge_kwh > 1e-9:
        share = discharge_kwh / len(discharging)
        for reserve in discharging:
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                discharged_kwh=share,
            )
    elif discharging:
        # Trigger without measured house discharge: hand off target over runtime.
        for reserve in discharging:
            target = float(reserve.get("target_kwh") or 0.0)
            runtime_h = max(0.25, target / max(0.1, float(reserve.get("target_kwh") or 0.1)))
            # Fall back: consume a slot share of target.
            step = target * min(1.0, dt_h / max(runtime_h, dt_h))
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                discharged_kwh=step,
            )

    _ = asap_total  # documented equal-share uses needing list above


def physical_charge_setpoints_kw(
    reserves: list[dict[str, Any]],
) -> dict[str, float]:
    """per powerstation_id → charge kW (0 when standby/full or discharging)."""
    out: dict[str, float] = {}
    for reserve in physical_reserves(reserves):
        ps_id = str(reserve["powerstation_id"])
        asap = float(reserve.get("asap_charge_kwh") or 0.0)
        max_charge = float(reserve.get("max_charge_power_kw") or 0.0)
        if asap > 1e-9 and max_charge > 0.0:
            out[ps_id] = max_charge
        else:
            out[ps_id] = 0.0
    return out


def appliance_is_reserve_mode(appliance: dict) -> bool:
    return str(appliance.get("mode") or "") == MODE_RESERVE


def write_physical_powerstation_charges(charge_kw_by_id: dict[str, float]) -> None:
    """Write Pattern-B ``ess.{slug}.set_ess_charge_power_limit``; discharge always 0."""
    if not charge_kw_by_id:
        return
    try:
        from ehal.ess_fields import ess_field
        from integrations import ehal_live
        from runtime_store.shadow.writes import should_invoke_setpoint_writes
    except Exception as exc:  # noqa: BLE001
        logger.warning("physical powerstation write skipped: %s", exc)
        return
    if not should_invoke_setpoint_writes(silent=config.is_loxone_silent_mode()):
        return
    if not ehal_live.is_ehal_network_backend():
        return
    adapter = ehal_live.get_adapter()
    setpoint: dict[str, Any] = {}
    for ps_id, charge_kw in charge_kw_by_id.items():
        slug = str(ps_id).strip()
        if not slug:
            continue
        charge_w = max(0.0, float(charge_kw) * 1000.0)
        setpoint[ess_field(slug, "set_ess_charge_power_limit")] = charge_w
        setpoint[ess_field(slug, "set_ess_discharge_power_limit")] = 0.0
    if not setpoint:
        return
    error = adapter.write_setpoints(setpoint)
    if error is not None:
        logger.warning("physical powerstation setpoints failed: %s", error)
