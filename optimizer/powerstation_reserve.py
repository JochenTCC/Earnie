"""Virtual/physical single_use powerstation reserve logic (2.7.g)."""
from __future__ import annotations

import logging
from typing import Any

from house_config.powerstation import (
    BACKING_PHYSICAL,
    BACKING_VIRTUAL,
    MODE_RESERVE,
    ROLE_SINGLE_USE,
    is_powerstation,
)
from runtime_store.powerstation_reserves import (
    STATE_CHARGING,
    STATE_DISCHARGING,
    STATE_EMPTY,
    STATE_STANDBY,
    clear_refill_opened,
    ensure_refill_opened,
    get_or_init_state,
    load_reserve_states,
    refill_deadline_utc,
    save_reserve_states,
)

logger = logging.getLogger(__name__)

TRIGGER_POWER_KW = 0.05


def reserve_target_kwh(
    *,
    default_power_kw: float,
    default_runtime_h: float,
    learned_kwh: float | None = None,
) -> float:
    if learned_kwh is not None and learned_kwh > 0.0:
        return float(learned_kwh)
    return max(0.0, float(default_power_kw) * float(default_runtime_h))


def protected_kwh_from_state(entry: dict[str, Any]) -> float:
    """kWh that house loads must not draw from the multi-ESS pool."""
    state = str(entry.get("state") or STATE_EMPTY)
    stored = max(0.0, float(entry.get("stored_kwh") or 0.0))
    target = max(0.0, float(entry.get("target_kwh") or 0.0))
    if state == STATE_DISCHARGING:
        return 0.0
    if state == STATE_STANDBY:
        return target if target > 0 else stored
    if state in (STATE_CHARGING, STATE_EMPTY):
        return stored
    return 0.0


def asap_charge_kwh_from_state(entry: dict[str, Any]) -> float:
    """kWh still needed ASAP into the virtual carve-out."""
    state = str(entry.get("state") or STATE_EMPTY)
    if state not in (STATE_EMPTY, STATE_CHARGING):
        return 0.0
    target = max(0.0, float(entry.get("target_kwh") or 0.0))
    stored = max(0.0, float(entry.get("stored_kwh") or 0.0))
    return max(0.0, target - stored)


def _group_reserve_appliances(
    appliances: list[dict],
    ps_by_id: dict[str, dict],
) -> dict[str, list[dict]]:
    """powerstation_id → reserve appliances (single_use PS only)."""
    groups: dict[str, list[dict]] = {}
    for appliance in appliances:
        if str(appliance.get("mode") or "") != MODE_RESERVE:
            continue
        ps_id = str(appliance.get("powerstation_id") or "").strip()
        if not ps_id:
            continue
        ps = ps_by_id.get(ps_id)
        if ps is None or not is_powerstation(ps):
            logger.warning(
                "Reserve appliance %s: powerstation_id '%s' fehlt oder ist keine Powerstation.",
                appliance.get("id"),
                ps_id,
            )
            continue
        if str(ps.get("role") or ROLE_SINGLE_USE) != ROLE_SINGLE_USE:
            continue
        groups.setdefault(ps_id, []).append(appliance)
    return groups


def _reserve_target_for_group(
    appliances: list[dict],
    *,
    ps: dict,
    learned_kwh: float | None,
) -> float:
    """Sum per-appliance targets; cap by pack/carve-out capacity."""
    total = 0.0
    for appliance in appliances:
        total += reserve_target_kwh(
            default_power_kw=float(appliance.get("default_power_kw") or 0.0),
            default_runtime_h=float(appliance.get("default_runtime_h") or 0.0),
            learned_kwh=learned_kwh if len(appliances) == 1 else None,
        )
    capacity = float(ps.get("battery_capacity_kwh") or 0.0)
    if capacity > 0.0:
        total = min(total, capacity)
    return total


def collect_active_reserves(
    *,
    appliances: list[dict],
    powerstations: list[dict] | dict[str, dict],
    learned_kwh_by_ps: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build runtime reserve specs — one entry per powerstation (shared pool)."""
    if isinstance(powerstations, dict):
        ps_by_id = dict(powerstations)
    else:
        ps_by_id = {str(p["id"]): p for p in powerstations if isinstance(p, dict)}

    states = load_reserve_states()
    learned = learned_kwh_by_ps or {}
    active: list[dict[str, Any]] = []
    dirty = False

    for ps_id, group in _group_reserve_appliances(appliances, ps_by_id).items():
        ps = ps_by_id[ps_id]
        entry_preview = states.get(ps_id) or {}
        learned_val = learned.get(ps_id)
        if learned_val is None and entry_preview.get("learned_kwh") is not None:
            learned_val = float(entry_preview["learned_kwh"])
        target = _reserve_target_for_group(
            group, ps=ps, learned_kwh=learned_val
        )
        entry = get_or_init_state(states, ps_id, target_kwh=target)
        dirty = True
        appliance_ids = [
            str(a.get("id") or "").strip()
            for a in group
            if str(a.get("id") or "").strip()
        ]
        deadline = refill_deadline_utc(entry)
        active.append(
            {
                "powerstation_id": ps_id,
                "appliance_id": appliance_ids[0] if appliance_ids else "",
                "appliance_ids": appliance_ids,
                "backing": str(ps.get("backing") or BACKING_VIRTUAL),
                "role": str(ps.get("role") or ROLE_SINGLE_USE),
                "state": entry["state"],
                "stored_kwh": float(entry["stored_kwh"]),
                "target_kwh": float(entry["target_kwh"]),
                "trigger_active": bool(entry.get("trigger_active")),
                "protected_kwh": protected_kwh_from_state(entry),
                "asap_charge_kwh": asap_charge_kwh_from_state(entry),
                "refill_kwh": asap_charge_kwh_from_state(entry),
                "refill_opened_at": entry.get("refill_opened_at"),
                "refill_deadline_utc": deadline.isoformat() if deadline else None,
                "max_charge_power_kw": float(
                    ps.get("battery_max_charge_power_kw")
                    or ps.get("max_charge_power_kw")
                    or 0.0
                ),
            }
        )

    if dirty:
        save_reserve_states(states)
    return active


def virtual_protected_kwh(reserves: list[dict[str, Any]]) -> float:
    return sum(
        float(r["protected_kwh"])
        for r in reserves
        if r.get("backing") == BACKING_VIRTUAL
    )


def virtual_asap_charge_kwh(reserves: list[dict[str, Any]]) -> float:
    return sum(
        float(r["asap_charge_kwh"])
        for r in reserves
        if r.get("backing") == BACKING_VIRTUAL
    )


def virtual_refill_deadline_iso(reserves: list[dict[str, Any]]) -> str | None:
    """Earliest refill deadline among virtual reserves that still need energy."""
    earliest: str | None = None
    for reserve in reserves:
        if reserve.get("backing") != BACKING_VIRTUAL:
            continue
        if float(reserve.get("refill_kwh") or 0.0) <= 1e-9:
            continue
        stamp = str(reserve.get("refill_deadline_utc") or "").strip()
        if not stamp:
            continue
        if earliest is None or stamp < earliest:
            earliest = stamp
    return earliest


def apply_virtual_reserve_floor(
    battery_params: dict | list[dict],
    *,
    protected_kwh: float,
    asap_charge_kwh: float = 0.0,
    refill_deadline_utc: str | None = None,
) -> dict | list[dict]:
    """Raise primary house ESS min_soc so protected kWh cannot serve other loads."""
    if isinstance(battery_params, list):
        if not battery_params:
            return battery_params
        out = [dict(b) for b in battery_params]
        if protected_kwh > 1e-9:
            _raise_min_soc(out[0], protected_kwh)
        if asap_charge_kwh > 1e-9:
            # refill_kwh: cost-optimal fill with deadline (2.7.p); alias kept for tests.
            out[0]["_virtual_reserve_refill_kwh"] = float(asap_charge_kwh)
            out[0]["_virtual_reserve_asap_kwh"] = float(asap_charge_kwh)
            if refill_deadline_utc:
                out[0]["_virtual_reserve_refill_deadline_utc"] = str(refill_deadline_utc)
        return out
    out = dict(battery_params)
    if protected_kwh > 1e-9:
        _raise_min_soc(out, protected_kwh)
    if asap_charge_kwh > 1e-9:
        out["_virtual_reserve_refill_kwh"] = float(asap_charge_kwh)
        out["_virtual_reserve_asap_kwh"] = float(asap_charge_kwh)
        if refill_deadline_utc:
            out["_virtual_reserve_refill_deadline_utc"] = str(refill_deadline_utc)
    return out


def prepare_battery_params_for_reserves(
    battery_params: dict | list[dict],
    reserves: list[dict[str, Any]],
) -> dict | list[dict]:
    """Apply virtual floor + refill-deadline metadata for the live/MILP call."""
    return apply_virtual_reserve_floor(
        battery_params,
        protected_kwh=virtual_protected_kwh(reserves),
        asap_charge_kwh=virtual_asap_charge_kwh(reserves),
        refill_deadline_utc=virtual_refill_deadline_iso(reserves),
    )


def _raise_min_soc(bat: dict, protected_kwh: float) -> None:
    capacity = float(bat.get("battery_capacity_kwh") or 0.0)
    if capacity <= 1e-9:
        return
    min_soc = float(bat.get("min_soc", bat.get("battery_min_soc") or 0.0) or 0.0)
    max_soc = float(bat.get("max_soc", bat.get("battery_max_soc") or 100.0) or 100.0)
    base_energy = (min_soc / 100.0) * capacity
    new_energy = base_energy + float(protected_kwh)
    new_soc = min(max_soc - 0.01, (new_energy / capacity) * 100.0)
    if "min_soc" in bat or "max_soc" in bat:
        bat["min_soc"] = max(min_soc, new_soc)
    else:
        bat["battery_min_soc"] = max(min_soc, new_soc)


def physical_reserves(reserves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in reserves if r.get("backing") == BACKING_PHYSICAL]


def advance_reserve_after_slot(
    *,
    powerstation_id: str,
    charged_kwh: float = 0.0,
    discharged_kwh: float = 0.0,
) -> dict[str, Any]:
    """Update stored energy / state after a planning slot (or trigger handoff)."""
    states = load_reserve_states()
    entry = get_or_init_state(states, powerstation_id, target_kwh=0.0)
    target = max(0.0, float(entry.get("target_kwh") or 0.0))
    stored = max(0.0, float(entry.get("stored_kwh") or 0.0))
    state = str(entry.get("state") or STATE_EMPTY)

    if state == STATE_DISCHARGING or entry.get("trigger_active"):
        stored = max(0.0, stored - max(0.0, discharged_kwh))
        if stored <= 1e-6:
            entry["state"] = STATE_EMPTY
            entry["stored_kwh"] = 0.0
            entry["trigger_active"] = False
            entry["refill_opened_at"] = None
            ensure_refill_opened(entry)
        else:
            entry["state"] = STATE_DISCHARGING
            entry["stored_kwh"] = stored
        save_reserve_states(states)
        return entry

    stored = min(target, stored + max(0.0, charged_kwh))
    entry["stored_kwh"] = stored
    if target <= 1e-9:
        entry["state"] = STATE_EMPTY
        ensure_refill_opened(entry)
    elif stored + 1e-6 >= target:
        entry["state"] = STATE_STANDBY
        clear_refill_opened(entry)
    else:
        entry["state"] = STATE_CHARGING
        ensure_refill_opened(entry)
    save_reserve_states(states)
    return entry


def detect_trigger_from_power(power_kw: float | None, *, threshold_kw: float = TRIGGER_POWER_KW) -> bool:
    if power_kw is None:
        return False
    return float(power_kw) >= float(threshold_kw)


def learn_energy_from_series(power_kw_series: list[float], *, dt_h: float) -> float | None:
    """Sum kWh above trigger threshold; None if series empty / no run."""
    if not power_kw_series or dt_h <= 0:
        return None
    energy = 0.0
    saw_run = False
    for power in power_kw_series:
        value = float(power or 0.0)
        if value >= TRIGGER_POWER_KW:
            saw_run = True
            energy += value * dt_h
    if not saw_run or energy <= 0.0:
        return None
    return energy


def update_learned_target(
    powerstation_id: str,
    power_kw_series: list[float],
    *,
    dt_h: float,
) -> float | None:
    """Persist learned kWh/run into reserve state; returns learned value or None."""
    learned = learn_energy_from_series(power_kw_series, dt_h=dt_h)
    if learned is None:
        return None
    states = load_reserve_states()
    entry = get_or_init_state(states, powerstation_id, target_kwh=learned)
    entry["learned_kwh"] = float(learned)
    entry["target_kwh"] = float(learned)
    save_reserve_states(states)
    return learned
