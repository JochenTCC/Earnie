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
    clear_fill_basis,
    clear_refill_opened,
    ensure_refill_opened,
    get_or_init_state,
    load_reserve_states,
    save_reserve_states,
)

from .reserve_price_floor import (
    BASE_MIN_SOC_KEY,
    BASIS_AT_KEY,
    BASIS_PRICE_KEY,
    FLOOR_SOC_KEY,
    RESERVE_KWH_KEY,
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
    *,
    warn: bool = True,
) -> dict[str, list[dict]]:
    """powerstation_id → reserve appliances (single_use PS only).

    ``warn=False`` for the 30 s wait-loop check: the cycle warns once per run.
    """
    groups: dict[str, list[dict]] = {}
    for appliance in appliances:
        if str(appliance.get("mode") or "") != MODE_RESERVE:
            continue
        ps_id = str(appliance.get("powerstation_id") or "").strip()
        if not ps_id:
            continue
        ps = ps_by_id.get(ps_id)
        if ps is None or not is_powerstation(ps):
            if not warn:
                continue
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
                "fill_basis_price": entry.get("fill_basis_price"),
                "fill_basis_at": entry.get("fill_basis_at"),
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


def virtual_reserve_kwh(reserves: list[dict[str, Any]]) -> float:
    """kWh the virtual reserves need in the battery where they pay (Reserve P2).

    Protected plus still missing energy: the target of every reserve that is not released.
    """
    return virtual_protected_kwh(reserves) + virtual_asap_charge_kwh(reserves)


def virtual_fill_basis(reserves: list[dict[str, Any]]) -> tuple[float, str] | None:
    """Cheapest persisted fill basis (price, UTC timestamp) among the virtual reserves."""
    best: tuple[float, str] | None = None
    for reserve in reserves:
        if reserve.get("backing") != BACKING_VIRTUAL:
            continue
        price = reserve.get("fill_basis_price")
        if price is None:
            continue
        stamp = reserve.get("fill_basis_at")
        if not stamp:
            raise ValueError(
                f"Reserve {reserve.get('powerstation_id')}: fill_basis_price ohne fill_basis_at."
            )
        if best is None or float(price) < best[0]:
            best = (float(price), str(stamp))
    return best


def apply_virtual_reserve_floor(
    battery_params: dict | list[dict],
    *,
    reserve_kwh: float,
    fill_basis: tuple[float, str] | None = None,
) -> dict | list[dict]:
    """Mark the primary house ESS with the virtual reserve (price-aware floor, Reserve P2).

    ``min_soc`` stays the configured value. The MILP raises the energy bound to
    ``_virtual_reserve_floor_soc`` only in the slots where the reserve pays
    (``optimizer.reserve_price_floor``).
    """
    if isinstance(battery_params, list):
        if not battery_params:
            return battery_params
        out = [dict(b) for b in battery_params]
        if reserve_kwh > 1e-9:
            _set_reserve_floor(out[0], reserve_kwh, fill_basis)
        return out
    out = dict(battery_params)
    if reserve_kwh > 1e-9:
        _set_reserve_floor(out, reserve_kwh, fill_basis)
    return out


def prepare_battery_params_for_reserves(
    battery_params: dict | list[dict],
    reserves: list[dict[str, Any]],
) -> dict | list[dict]:
    """Apply the virtual reserve and its fill basis for the live/MILP call.

    The SoC reading resolution is handled per slot from the start energy
    (Reserve P3, ``reserve_price_floor.banded_floor_kwh``).
    """
    return apply_virtual_reserve_floor(
        battery_params,
        reserve_kwh=virtual_reserve_kwh(reserves),
        fill_basis=virtual_fill_basis(reserves),
    )


_FLOOR_SOC_KEY = FLOOR_SOC_KEY
_BASE_MIN_SOC_KEY = BASE_MIN_SOC_KEY
# Read by the MILP: the configured min_soc below the virtual reserve floor.
VIRTUAL_RESERVE_BASE_MIN_SOC_KEY = _BASE_MIN_SOC_KEY


def _primary(battery_params: dict | list[dict]) -> dict | None:
    if isinstance(battery_params, list):
        return battery_params[0] if battery_params else None
    return battery_params


def reserve_floor_discharge_cap_kw(
    battery_params: dict | list[dict],
    current_soc: float,
    *,
    dt_h: float,
    matrix: list[dict[str, Any]],
) -> float | None:
    """Highest Automatik discharge power that keeps the virtual reserve for the current slot.

    In Automatik the plant follows its own rule down to its own minimum SoC, so a large flex
    load can drain the virtual reserve within one slot, and the next cycle refills it from the
    grid. Capping the written discharge limit at the energy above the floor at the end of the
    current slot (after the idle drain of the slot, AC side through the path efficiency)
    prevents that. The floor is the MILP's (``effective_floor_kwh``): a reading inside the
    tolerance band, also one step above the floor, gives no release (Reserve P3). ``None``
    without a virtual reserve or when the reserve is not held in the current slot (Reserve P2:
    no floor, no cap).
    """
    from .battery import idle_drain_soc_pct
    from .reserve_price_floor import effective_floor_kwh

    bat = _primary(battery_params)
    if bat is None or _FLOOR_SOC_KEY not in bat:
        return None
    if dt_h <= 0.0:
        raise ValueError(f"reserve_floor_discharge_cap_kw: dt_h must be > 0, got {dt_h}")
    if "efficiency" not in bat:
        raise ValueError("reserve_floor_discharge_cap_kw: battery params without efficiency")
    capacity = float(bat["battery_capacity_kwh"])
    soc = float(current_soc)
    e_init = soc / 100.0 * capacity
    effective = effective_floor_kwh(bat, matrix, horizon=len(matrix), e_init=e_init, dt_h=dt_h)
    if effective is None or not effective[0].held_now:
        return None
    drain_kwh = idle_drain_soc_pct(soc, bat, dt_h=dt_h) / 100.0 * capacity
    above_kwh = max(0.0, e_init - drain_kwh - effective[1][0])
    return above_kwh * float(bat["efficiency"]) / float(dt_h)


def _set_reserve_floor(
    bat: dict, reserve_kwh: float, fill_basis: tuple[float, str] | None
) -> None:
    capacity = float(bat.get("battery_capacity_kwh") or 0.0)
    if capacity <= 1e-9:
        return
    min_soc = float(bat.get("min_soc", bat.get("battery_min_soc") or 0.0) or 0.0)
    max_soc = float(bat.get("max_soc", bat.get("battery_max_soc") or 100.0) or 100.0)
    base_energy = (min_soc / 100.0) * capacity
    new_soc = min(max_soc - 0.01, ((base_energy + float(reserve_kwh)) / capacity) * 100.0)
    bat[RESERVE_KWH_KEY] = float(reserve_kwh)
    bat[_FLOOR_SOC_KEY] = max(min_soc, new_soc)
    bat[_BASE_MIN_SOC_KEY] = min_soc
    if fill_basis is not None:
        bat[BASIS_PRICE_KEY] = float(fill_basis[0])
        bat[BASIS_AT_KEY] = str(fill_basis[1])


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
    # Preserve configured/learned target — never overwrite with placeholder 0.
    entry = get_or_init_state(
        states, powerstation_id, target_kwh=0.0, update_target=False
    )
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
            clear_fill_basis(entry)
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
