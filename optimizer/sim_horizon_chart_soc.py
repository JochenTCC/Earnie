"""Battery resolution and per-ESS chart SoC bookkeeping of the horizon simulation (split from simulation)."""
from __future__ import annotations

import logging
import config
from .milp_horizon import (
    aggregate_battery_params_for_load,
    coerce_battery_params_list,
)
from .sim_chart_rows import (
    COL_BATTERIE_AKTION,
    COL_SOC,
)
from .slot_duration import DEFAULT_DT_H
from optimizer.sim_horizon_types import (
    _HorizonSetup,
)


def _resolve_horizon_batteries(
    battery_params: dict | list[dict] | None,
) -> tuple[list[dict], dict]:
    """Return (batteries list, aggregate params) for MILP + chart SoC."""
    if battery_params is None:
        get_list = getattr(config, "get_battery_params_list", None)
        if callable(get_list):
            listed = get_list()
            if listed:
                batteries = coerce_battery_params_list(listed)
                return batteries, aggregate_battery_params_for_load(batteries)
        battery_params = config.get_battery_params()
    batteries = coerce_battery_params_list(battery_params)
    if not batteries:
        agg = battery_params if isinstance(battery_params, dict) else {}
        return [], agg
    return batteries, aggregate_battery_params_for_load(batteries)


def _resolve_chart_soc_entities(batteries: list[dict]) -> tuple[dict, ...]:
    """House MILP batteries plus planning powerstations for Chart1 SoC columns."""
    from house_config.entity_resolution import battery_params_from_planning
    from optimizer.powerstation_soc_chart import chart_soc_entities

    powerstations: list[dict] = []
    try:
        resolved = config.get_resolved_runtime_settings() or {}
    except Exception:  # noqa: BLE001
        resolved = {}
    for entry in resolved.get("_planning_powerstations") or []:
        if not isinstance(entry, dict) or not str(entry.get("id") or "").strip():
            continue
        try:
            powerstations.append(battery_params_from_planning(entry))
        except (KeyError, TypeError, ValueError):
            powerstations.append(entry)
    return tuple(chart_soc_entities(batteries, powerstations))


def _resolve_standby_chart_plans(
    matrix: list,
    current_soc_by_id: dict[str, float] | None,
) -> tuple[dict, dict]:
    """Standby island/charge plan + pack meta for Chart1 physical PS SoC."""
    if not current_soc_by_id:
        return {}, {}
    try:
        from optimizer.powerstation_live import load_standby_packs
        from optimizer.powerstation_standby import plan_standby_horizon

        packs = load_standby_packs()
        if not packs:
            return {}, {}
        packs_by_id = {
            str(p["powerstation_id"]): p
            for p in packs
            if str(p.get("powerstation_id") or "").strip()
        }
        plans = plan_standby_horizon(
            matrix,
            packs,
            current_soc_by_id=current_soc_by_id,
            dt_h=DEFAULT_DT_H,
        )
        return plans or {}, packs_by_id
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "standby chart SoC plan unavailable: %s", exc
        )
        return {}, {}


def _initial_soc_by_ess(
    setup: _HorizonSetup,
    initial_soc: float,
) -> dict[str, float]:
    """Start SoC map for Chart1 columns (no primary substitute for missing house ESS)."""
    by_id = dict(setup.current_soc_by_id or {})
    entities = list(setup.chart_soc_entities) or [
        {
            "id": str(b.get("id") or "").strip(),
            "label": str(b.get("label") or b.get("id") or "").strip(),
            "virtual": False,
        }
        for b in setup.batteries
        if str(b.get("id") or "").strip()
    ]
    house_ids = {
        str(b.get("id") or "").strip()
        for b in setup.batteries
        if str(b.get("id") or "").strip()
    }
    multi_house = len(house_ids) > 1
    out: dict[str, float] = {}
    for entity in entities:
        ess_id = str(entity.get("id") or "").strip()
        if not ess_id:
            continue
        if ess_id in by_id:
            out[ess_id] = float(by_id[ess_id])
        elif ess_id in house_ids and not multi_house:
            out[ess_id] = float(initial_soc)
        # physical PS / second house: omit when missing — no silent primary fill
    return out


def _seed_virtual_soc_for_chart(
    setup: _HorizonSetup,
    soc_by_ess: dict[str, float],
) -> list[dict]:
    """Seed virtual PS SoC into ``soc_by_ess``; return mutable sim entries."""
    from optimizer.powerstation_soc_chart import (
        initial_virtual_sim_entries,
        soc_percent_map_for_entities,
    )
    from runtime_store.powerstation_reserves import load_reserve_states

    virtual_ps = [
        {
            "id": e["id"],
            "battery_capacity_kwh": e.get("battery_capacity_kwh", 0.0),
            "type": "powerstation",
            "backing": "virtual",
        }
        for e in setup.chart_soc_entities
        if e.get("virtual")
    ]
    if not virtual_ps:
        return []
    try:
        states = load_reserve_states()
    except Exception:  # noqa: BLE001
        states = {}
    entries = initial_virtual_sim_entries(
        powerstations=virtual_ps, reserve_states=states
    )
    soc_by_ess.update(
        soc_percent_map_for_entities(list(setup.chart_soc_entities), entries)
    )
    return entries


def _advance_chart_soc_after_slot(
    setup: _HorizonSetup,
    chart_row: dict,
    soc_by_ess: dict[str, float],
    *,
    slot: dict | None,
    slot_index: int,
    virtual_entries: list[dict],
    end_soc: float | None = None,
) -> None:
    """Update house / physical-standby / virtual SoC maps for the next Chart1 attach."""
    from optimizer.powerstation_soc_chart import simulate_virtual_reserve_soc_after_slot
    from optimizer.powerstation_standby import advance_physical_standby_soc_after_slot

    planned_by = (slot or {}).get("planned_soc_by_ess") or {}
    if planned_by:
        for ess_id, soc_val in planned_by.items():
            soc_by_ess[str(ess_id)] = float(soc_val)
    else:
        house_ids = [
            str(b.get("id") or "").strip()
            for b in setup.batteries
            if str(b.get("id") or "").strip()
        ]
        if len(house_ids) == 1:
            # End-of-slot SoC for the controlled ESS (Steuerbefehl / plant battery).
            # COL_SOC is start-of-slot — never write it back here.
            if end_soc is not None:
                soc_by_ess[house_ids[0]] = float(end_soc)
            elif COL_SOC in chart_row and house_ids[0] not in soc_by_ess:
                soc_by_ess[house_ids[0]] = float(chart_row[COL_SOC])
    if setup.standby_plans:
        advance_physical_standby_soc_after_slot(
            soc_by_ess,
            plans=setup.standby_plans,
            packs_by_id=setup.standby_packs_by_id or {},
            slot_index=slot_index,
            dt_h=DEFAULT_DT_H,
        )
    if virtual_entries:
        plan_kw = float(chart_row.get(COL_BATTERIE_AKTION, 0.0) or 0.0)
        soc_by_ess.update(
            simulate_virtual_reserve_soc_after_slot(
                battery_plan_kw=plan_kw,
                dt_h=DEFAULT_DT_H,
                virtual_entries=virtual_entries,
            )
        )
