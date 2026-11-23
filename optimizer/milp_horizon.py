"""MILP-Horizontmodell: Variablen, Energiebilanz, SOC-Randbedingungen, Zielfunktion."""
from __future__ import annotations

import logging
from typing import Any

import pulp

logger = logging.getLogger(__name__)

from .battery import IDLE_DRAIN_KEY, effective_p_act, idle_drain_floor_soc, idle_drain_kw  # noqa: F401
from .consumer_power import power_limits_kw
from .milp_control_slot import (  # noqa: F401  (re-exported)
    _add_control_slot_constraints,
    _add_self_consumption_coupling,
)
from .milp_plant import (  # noqa: F401  (re-exported)
    coerce_battery_params_list,
    plant_battery_params,
    plant_energy_params,
    plant_soc_params,
    plant_soc_percent,
    plant_soc_view,
    primary_battery_with_plant_power,
)
from .eauto_milp import milp_binary_charge_kw
from .milp_consumers import (
    _add_consumer_power_variables,
    _flex_power_at_t,
)
from .milp_inverter import (
    coerce_inverter_params_list,
    coerce_pv_systems_list,
    filter_house_balance_batteries,
    house_balance_pv_kw,
    add_inverter_slot_constraints,
)
from .milp_soc_recovery import add_soc_recovery_constraints
from .slot_duration import DEFAULT_DT_H, validate_dt_h
from optimizer.milp_horizon_extras import (  # noqa: F401  (re-exported)
    _add_milp_objective,
    _add_pv_only_charge_through_sunrise,
    _add_soc_equality_constraint,
    _add_sunrise_soc_min_constraint,
    _add_terminal_soc_constraint,
    _terminal_soc_energy_kwh,
)
from optimizer.milp_horizon_types import (  # noqa: F401  (re-exported)
    MilpHorizonModel,
    _ConsumerVarBlock,
    _GridBatteryVars,
)

EMPTY_MILP_PLAN = {
    "p_grid_buy": 0.0,
    "p_grid_sell": 0.0,
    "p_charge": 0.0,
    "p_discharge": 0.0,
    "p_pv_curtail": 0.0,
    "ess": {},
}


def _normalize_fixed_flex_by_t(
    fixed_flex_kw_t0_or_by_t: float | dict[int, float] | None,
) -> dict[int, float]:
    """Accept legacy t0 float or hour→kW map for preset flex outside MILP vars."""
    if fixed_flex_kw_t0_or_by_t is None:
        return {}
    if isinstance(fixed_flex_kw_t0_or_by_t, (int, float)):
        value = float(fixed_flex_kw_t0_or_by_t)
        return {0: value} if value > 1e-12 else {}
    return {
        int(slot): float(power)
        for slot, power in fixed_flex_kw_t0_or_by_t.items()
        if float(power) > 1e-12
    }


def _create_grid_battery_vars(
    matrix: list[dict[str, Any]],
    horizon: int,
    battery_params: dict | list[dict],
    planned_consumers: list,
    fixed_flex_by_t: dict[int, float],
    *,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
) -> _GridBatteryVars:
    """LpVariables für Netzbezug/-einspeisung, Lade-/Entladeleistung und SOC-Energie."""
    inverters = coerce_inverter_params_list(inverter_params)
    pv_list = coerce_pv_systems_list(pv_systems)
    batteries = filter_house_balance_batteries(
        coerce_battery_params_list(battery_params), inverters
    )
    if not batteries:
        batteries = [
            {
                "id": "primary",
                "battery_capacity_kwh": 0.0,
                "min_soc": 0.0,
                "max_soc": 100.0,
                "max_charge_power_kw": 0.0,
                "max_discharge_power_kw": 0.0,
                "max_power_kw": 0.0,
                "efficiency": 1.0,
                "standby_power_kw": 0.0,
                "control": "full",
            }
        ]
    load_params = primary_battery_with_plant_power(batteries)
    ess_ids: list[str] = []
    params_by_id: dict[str, dict] = {}
    p_charge_by_ess: dict[str, list] = {}
    p_discharge_by_ess: dict[str, list] = {}
    e_batt_by_ess: dict[str, list] = {}
    delta_charge_by_ess: dict[str, list] = {}

    for index, bat in enumerate(batteries):
        ess_id = str(bat.get("id") or f"ess_{index}").strip() or f"ess_{index}"
        ess_ids.append(ess_id)
        params_by_id[ess_id] = bat
        max_charge = float(bat.get("max_charge_power_kw", bat.get("max_power_kw") or 0.0) or 0.0)
        max_discharge = float(
            bat.get("max_discharge_power_kw", bat.get("max_power_kw") or 0.0) or 0.0
        )
        capacity = float(bat.get("battery_capacity_kwh") or 0.0)
        min_soc = float(bat.get("min_soc") or 0.0)
        max_soc = float(bat.get("max_soc") or 100.0)
        e_min = (min_soc / 100.0) * capacity
        e_max = (max_soc / 100.0) * capacity
        slug = ess_id.replace("-", "_")
        p_charge_by_ess[ess_id] = [
            pulp.LpVariable(f"p_charge_{slug}_{t}", lowBound=0, upBound=max_charge)
            for t in range(horizon)
        ]
        p_discharge_by_ess[ess_id] = [
            pulp.LpVariable(f"p_discharge_{slug}_{t}", lowBound=0, upBound=max_discharge)
            for t in range(horizon)
        ]
        e_batt_by_ess[ess_id] = [
            pulp.LpVariable(f"e_batt_{slug}_{t}", lowBound=e_min, upBound=e_max)
            for t in range(horizon)
        ]
        delta_charge_by_ess[ess_id] = [
            pulp.LpVariable(f"delta_charge_{slug}_{t}", cat=pulp.LpBinary)
            for t in range(horizon)
        ]

    max_charge_sum = float(load_params["max_charge_power_kw"])
    max_discharge_sum = float(load_params["max_discharge_power_kw"])
    max_power = float(load_params["max_power_kw"])
    # Aggregate vars = sum of ESS (compat for objective / terminal / extract)
    p_grid_buy = [pulp.LpVariable(f"p_grid_buy_{t}", lowBound=0) for t in range(horizon)]
    p_grid_sell = [pulp.LpVariable(f"p_grid_sell_{t}", lowBound=0) for t in range(horizon)]
    p_charge = [
        pulp.LpVariable(f"p_charge_{t}", lowBound=0, upBound=max_charge_sum)
        for t in range(horizon)
    ]
    p_discharge = [
        pulp.LpVariable(f"p_discharge_{t}", lowBound=0, upBound=max_discharge_sum)
        for t in range(horizon)
    ]
    # Feasible sink when export is hard-capped (pay-to-export / plant limit) but PV
    # exceeds load + charge — without this the power balance is Infeasible.
    def _slot_house_pv(row: dict[str, Any]) -> float:
        return house_balance_pv_kw(
            row, inverters=inverters, pv_systems=pv_list
        )

    p_pv_curtail = [
        pulp.LpVariable(
            f"p_pv_curtail_{t}",
            lowBound=0,
            upBound=_slot_house_pv(matrix[t]),
        )
        for t in range(horizon)
    ]
    primary_id = ess_ids[0]
    # model.e_batt is the plan's SoC: the battery itself, or with several the energy of all
    # (tied to the sum in ``_add_slot_power_balance_and_soc``; bounds come from the batteries).
    e_batt = (
        e_batt_by_ess[primary_id]
        if len(ess_ids) == 1
        else [pulp.LpVariable(f"e_batt_plant_{t}") for t in range(horizon)]
    )
    delta_charge = delta_charge_by_ess[primary_id]
    max_flex_power = sum(power_limits_kw(c)[1] for c in planned_consumers)
    # Preset flex (e.g. fixed EV charging) is load outside the MILP vars: the Big-M must
    # cover it, or p_grid_buy is cut below the slot's real demand (wrong plan / Infeasible).
    max_load = max(
        (
            effective_p_act(row, load_params) + float(fixed_flex_by_t.get(t, 0.0))
            for t, row in enumerate(matrix[:horizon])
        ),
        default=0.0,
    )
    max_pv = max((_slot_house_pv(row) for row in matrix[:horizon]), default=0.0)
    big_m_grid = max(max_load + max_flex_power + max_power, max_pv + max_power, 50.0)
    delta_import = [
        pulp.LpVariable(f"delta_import_{t}", cat=pulp.LpBinary) for t in range(horizon)
    ]
    return _GridBatteryVars(
        p_grid_buy=p_grid_buy,
        p_grid_sell=p_grid_sell,
        p_charge=p_charge,
        p_discharge=p_discharge,
        p_pv_curtail=p_pv_curtail,
        e_batt=e_batt,
        delta_charge=delta_charge,
        delta_import=delta_import,
        big_m_grid=big_m_grid,
        ess_ids=ess_ids,
        p_charge_by_ess=p_charge_by_ess,
        p_discharge_by_ess=p_discharge_by_ess,
        e_batt_by_ess=e_batt_by_ess,
        delta_charge_by_ess=delta_charge_by_ess,
        battery_params_by_id=params_by_id,
    )


def _add_consumer_var_block(
    prob: pulp.LpProblem,
    matrix: list[dict[str, Any]],
    horizon: int,
    planned_consumers: list,
    remaining_by_consumer: dict[str, float],
    ev_milp_params_by_id: dict[str, dict[str, float]],
    consumer_continue_on: dict[str, bool] | None,
) -> _ConsumerVarBlock:
    """On/Leistung/PV-Follow je geplantem Verbraucher plus Binär-Ladeleistung."""
    block = _ConsumerVarBlock(
        consumer_on={},
        consumer_p={},
        consumer_p_fixed={},
        consumer_pv_follow={},
        consumer_milp_charge_kw={},
    )
    continue_on = consumer_continue_on or {}
    for consumer in planned_consumers:
        cid = consumer["id"]
        rem = remaining_by_consumer.get(cid, 0.0)
        ev_params = ev_milp_params_by_id.get(cid)
        block.consumer_milp_charge_kw[cid] = milp_binary_charge_kw(
            consumer, matrix, rem, ev_params
        )
        _add_consumer_power_variables(
            prob,
            consumer,
            horizon,
            matrix,
            block.consumer_on,
            block.consumer_p,
            block.consumer_p_fixed,
            block.consumer_pv_follow,
            rem,
            ev_params,
            continue_on=bool(continue_on.get(cid, False)),
        )
    return block


def _idle_drain_kwh_term(
    prob: pulp.LpProblem,
    bat: dict,
    eid: str,
    *,
    t: int,
    prev_e,
    dt_h: float,
):
    """Energy the idle drain takes from battery ``eid`` in slot ``t`` (Reserve P4).

    The drain applies while the energy at the start of the slot is above the drain floor
    (``idle_drain_floor_soc``). Slot 0 starts at a known energy: the drain is a constant, cut
    to the room above the floor as in the simulation (``apply_soc_change``). Later slots get a
    binary ``idle_drain_off``: it may only be 1 when the start energy lies within one slot's
    drain of the floor, and then the slot has no drain. Near the floor the plan is thus at most
    one slot's drain more optimistic than the simulation. Without drain the term is 0 and the
    model has no extra variables.
    """
    drain_kw = idle_drain_kw(bat)
    capacity = float(bat.get("battery_capacity_kwh") or 0.0)
    if drain_kw <= 0.0 or capacity <= 0.0:
        return 0.0
    drain_kwh = drain_kw * dt_h
    floor_kwh = idle_drain_floor_soc(bat) / 100.0 * capacity
    if t == 0:
        return min(drain_kwh, max(0.0, float(prev_e) - floor_kwh))
    slug = str(eid).replace("-", "_")
    off = pulp.LpVariable(f"idle_drain_off_{slug}_{t}", cat=pulp.LpBinary)
    prob += (
        prev_e - floor_kwh <= drain_kwh + capacity * (1 - off),
        f"idle_drain_floor_{slug}_{t}",
    )
    return drain_kwh * (1 - off)


def _add_slot_power_balance_and_soc(
    prob: pulp.LpProblem,
    matrix_row: dict[str, Any],
    battery_params: dict,
    grid_vars: _GridBatteryVars,
    consumer_vars: _ConsumerVarBlock,
    planned_consumers: list,
    fixed_flex: float,
    *,
    t: int,
    e_init_by_ess: dict[str, float],
    dt_h: float,
    export_cap_kw: float | None = None,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
) -> None:
    """Energiebilanz, Exklusivität und SOC-Rekursion für einen Slot."""
    load_params = battery_params
    max_power = float(load_params["max_power_kw"])
    p_grid_buy = grid_vars.p_grid_buy
    p_grid_sell = grid_vars.p_grid_sell
    p_charge = grid_vars.p_charge
    p_discharge = grid_vars.p_discharge
    delta_import = grid_vars.delta_import
    big_m_grid = grid_vars.big_m_grid
    inverters = coerce_inverter_params_list(inverter_params)
    pv_list = coerce_pv_systems_list(pv_systems)
    p_pv = house_balance_pv_kw(
        matrix_row, inverters=inverters, pv_systems=pv_list
    )
    p_con = effective_p_act(matrix_row, load_params)
    p_flex = fixed_flex + pulp.lpSum(
        _flex_power_at_t(
            consumer,
            consumer_vars.consumer_on,
            consumer_vars.consumer_p,
            consumer_vars.consumer_milp_charge_kw[consumer["id"]],
            t,
        )
        for consumer in planned_consumers
    )
    # Tie aggregates to per-ESS vars
    if len(grid_vars.ess_ids) > 1:
        prob += grid_vars.e_batt[t] == pulp.lpSum(
            grid_vars.e_batt_by_ess[eid][t] for eid in grid_vars.ess_ids
        )
    prob += p_charge[t] == pulp.lpSum(
        grid_vars.p_charge_by_ess[eid][t] for eid in grid_vars.ess_ids
    )
    prob += p_discharge[t] == pulp.lpSum(
        grid_vars.p_discharge_by_ess[eid][t] for eid in grid_vars.ess_ids
    )
    for eid in grid_vars.ess_ids:
        bat = grid_vars.battery_params_by_id[eid]
        max_c = float(bat.get("max_charge_power_kw", bat.get("max_power_kw") or 0.0) or 0.0)
        max_d = float(
            bat.get("max_discharge_power_kw", bat.get("max_power_kw") or 0.0) or 0.0
        )
        max_ess = max(max_c, max_d)
        delta = grid_vars.delta_charge_by_ess[eid][t]
        prob += grid_vars.p_charge_by_ess[eid][t] <= max_ess * delta
        prob += grid_vars.p_discharge_by_ess[eid][t] <= max_ess * (1 - delta)
        efficiency = float(bat.get("efficiency") or 1.0)
        e_batt = grid_vars.e_batt_by_ess[eid]
        prev_e = e_init_by_ess[eid] if t == 0 else e_batt[t - 1]
        prob += (
            e_batt[t]
            == prev_e
            + (
                grid_vars.p_charge_by_ess[eid][t] * efficiency
                - grid_vars.p_discharge_by_ess[eid][t] / efficiency
            )
            * dt_h
            - _idle_drain_kwh_term(prob, bat, eid, t=t, prev_e=prev_e, dt_h=dt_h)
        )
        _add_control_slot_constraints(
            prob,
            bat,
            t=t,
            p_pv=p_pv,
            p_con=p_con,
            p_flex=p_flex,
            p_grid_buy=p_grid_buy[t],
            p_grid_sell=p_grid_sell[t],
            p_charge=grid_vars.p_charge_by_ess[eid][t],
            p_discharge=grid_vars.p_discharge_by_ess[eid][t],
            delta_import=delta_import[t],
            max_power=max_ess,
            big_m_grid=big_m_grid,
            suffix=str(eid).replace("-", "_"),
            # Self-consumption pin is single-ESS only (multi would fight over grid).
            apply_self_consumption=len(grid_vars.ess_ids) == 1,
        )
    add_inverter_slot_constraints(
        prob,
        t=t,
        grid_vars=grid_vars,
        inverters=inverters,
        pv_systems=pv_list,
        matrix_row=matrix_row,
    )
    prob += (
        p_pv + p_grid_buy[t] + p_discharge[t]
        == p_con
        + p_flex
        + p_grid_sell[t]
        + p_charge[t]
        + grid_vars.p_pv_curtail[t]
    )
    prob += p_grid_buy[t] <= big_m_grid * delta_import[t]
    sell_upper = big_m_grid
    if export_cap_kw is not None:
        sell_upper = min(big_m_grid, max(0.0, float(export_cap_kw)))
    prob += p_grid_sell[t] <= sell_upper * (1 - delta_import[t])
    if export_cap_kw is not None:
        prob += p_grid_sell[t] <= max(0.0, float(export_cap_kw))


def _initial_energy_by_ess(
    grid_vars: _GridBatteryVars,
    current_soc: float,
    current_soc_by_id: dict[str, float] | None,
) -> dict[str, float]:
    """Stored energy [kWh] of each house battery at the plan start.

    One battery takes its SoC from ``current_soc_by_id`` when present, else ``current_soc``.
    Several batteries need each one's own SoC in ``current_soc_by_id``: one battery's SoC does
    not stand for another. A battery without capacity stores nothing and needs no SoC (as in
    ``plant_soc_percent``).

    Raises ``ValueError`` naming the batteries without SoC and the ids that are present.
    """
    by_id = current_soc_by_id or {}
    ess_ids = list(grid_vars.ess_ids)
    capacity_by_ess = {
        eid: float(grid_vars.battery_params_by_id[eid].get("battery_capacity_kwh") or 0.0)
        for eid in ess_ids
    }
    if len(ess_ids) == 1:
        eid = ess_ids[0]
        soc = float(by_id[eid]) if eid in by_id else float(current_soc)
        return {eid: (soc / 100.0) * capacity_by_ess[eid]}
    missing = [eid for eid in ess_ids if eid not in by_id and capacity_by_ess[eid] > 0.0]
    if missing:
        raise ValueError(
            f"MILP: Start-SoC fehlt für Hausbatterie(n) {missing} (vorhanden: {sorted(by_id)}); "
            "mit mehreren Hausbatterien braucht jede ihren eigenen SoC."
        )
    return {
        eid: (float(by_id[eid]) / 100.0) * capacity_by_ess[eid] if eid in by_id else 0.0
        for eid in ess_ids
    }


def _add_power_balance_and_soc_dynamics(
    prob: pulp.LpProblem,
    matrix: list[dict[str, Any]],
    battery_params: dict | list[dict],
    current_soc: float,
    grid_vars: _GridBatteryVars,
    consumer_vars: _ConsumerVarBlock,
    planned_consumers: list,
    fixed_flex_by_t: dict[int, float],
    *,
    horizon: int,
    dt_h: float,
    export_caps_kw: list[float | None] | None = None,
    current_soc_by_id: dict[str, float] | None = None,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
) -> dict[str, tuple[float, float]]:
    """Energiebilanz, Netz-/Batterie-Exklusivität und SOC-Rekursion je Slot.

    Returns the widened SoC range of batteries that start outside their limits
    (``add_soc_recovery_constraints``).
    """
    inverters = coerce_inverter_params_list(inverter_params)
    batteries = filter_house_balance_batteries(
        coerce_battery_params_list(battery_params), inverters
    )
    load_params = primary_battery_with_plant_power(batteries)
    e_init_by_ess = _initial_energy_by_ess(grid_vars, current_soc, current_soc_by_id)
    relaxed_soc_bounds = add_soc_recovery_constraints(prob, grid_vars, e_init_by_ess)
    for t in range(horizon):
        cap = None
        if export_caps_kw is not None and t < len(export_caps_kw):
            cap = export_caps_kw[t]
        _add_slot_power_balance_and_soc(
            prob,
            matrix[t],
            load_params,
            grid_vars,
            consumer_vars,
            planned_consumers,
            float(fixed_flex_by_t.get(t, 0.0)),
            t=t,
            e_init_by_ess=e_init_by_ess,
            dt_h=dt_h,
            export_cap_kw=cap,
            inverter_params=inverter_params,
            pv_systems=pv_systems,
        )
    return relaxed_soc_bounds


def _apply_reserve_price_floor(
    matrix: list[dict[str, Any]],
    horizon: int,
    grid_vars: _GridBatteryVars,
    current_soc: float,
    current_soc_by_id: dict[str, float] | None,
    *,
    dt_h: float,
) -> tuple[list[float], float] | None:
    """Raise the primary battery's energy bound in the slots where the reserve pays (Reserve P2).

    Returns the lower bound per slot (kWh, end of slot) and the primary battery's start energy,
    or ``None`` without a virtual reserve.
    A start inside the tolerance band at the floor is held (Reserve P3, ``banded_floor_kwh``);
    a floor the battery cannot reach from its start energy is lowered to what it can reach
    (``reachable_floor_kwh``). A start below the base ``min_soc`` is led back by
    ``add_soc_recovery_constraints`` with these per-slot bounds.
    """
    from .reserve_price_floor import effective_floor_kwh

    primary_id = grid_vars.ess_ids[0]
    bat = grid_vars.battery_params_by_id[primary_id]
    e_init = _initial_energy_by_ess(grid_vars, current_soc, current_soc_by_id)[primary_id]
    effective = effective_floor_kwh(bat, matrix, horizon=horizon, e_init=e_init, dt_h=dt_h)
    if effective is None:
        return None
    _plan, floors = effective
    for e_var, floor in zip(grid_vars.e_batt_by_ess[primary_id], floors):
        if floor > float(e_var.lowBound) + 1e-9:
            e_var.lowBound = min(floor, float(e_var.upBound))
    return [float(v.lowBound) for v in grid_vars.e_batt_by_ess[primary_id]], e_init


def _build_milp_model(
    matrix: list[dict[str, Any]],
    horizon: int,
    battery_params: dict | list[dict],
    current_soc: float,
    planned_consumers: list,
    fixed_flex_kw_t0_or_by_t: float | dict[int, float],
    remaining_by_consumer: dict[str, float],
    ev_milp_params_by_id: dict[str, dict[str, float]],
    consumer_continue_on: dict[str, bool] | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
    export_caps_kw: list[float | None] | None = None,
    current_soc_by_id: dict[str, float] | None = None,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
) -> MilpHorizonModel:
    dt_h = validate_dt_h(dt_h)
    prob = pulp.LpProblem("Energy_Cost_Minimization", pulp.LpMinimize)
    fixed_flex_by_t = _normalize_fixed_flex_by_t(fixed_flex_kw_t0_or_by_t)
    grid_vars = _create_grid_battery_vars(
        matrix,
        horizon,
        battery_params,
        planned_consumers,
        fixed_flex_by_t,
        inverter_params=inverter_params,
        pv_systems=pv_systems,
    )
    consumer_vars = _add_consumer_var_block(
        prob,
        matrix,
        horizon,
        planned_consumers,
        remaining_by_consumer,
        ev_milp_params_by_id,
        consumer_continue_on,
    )
    reserve_floor = _apply_reserve_price_floor(
        matrix, horizon, grid_vars, current_soc, current_soc_by_id, dt_h=dt_h
    )
    relaxed_soc_bounds = _add_power_balance_and_soc_dynamics(
        prob,
        matrix,
        battery_params,
        current_soc,
        grid_vars,
        consumer_vars,
        planned_consumers,
        fixed_flex_by_t,
        horizon=horizon,
        dt_h=dt_h,
        export_caps_kw=export_caps_kw,
        current_soc_by_id=current_soc_by_id,
        inverter_params=inverter_params,
        pv_systems=pv_systems,
    )
    return MilpHorizonModel(
        prob=prob,
        horizon=horizon,
        p_grid_buy=grid_vars.p_grid_buy,
        p_grid_sell=grid_vars.p_grid_sell,
        p_charge=grid_vars.p_charge,
        p_discharge=grid_vars.p_discharge,
        e_batt=grid_vars.e_batt,
        consumer_on=consumer_vars.consumer_on,
        consumer_p=consumer_vars.consumer_p,
        consumer_p_fixed=consumer_vars.consumer_p_fixed,
        consumer_pv_follow=consumer_vars.consumer_pv_follow,
        planned_consumers=planned_consumers,
        consumer_milp_charge_kw=consumer_vars.consumer_milp_charge_kw,
        dt_h=dt_h,
        ess_ids=list(grid_vars.ess_ids),
        p_charge_by_ess=dict(grid_vars.p_charge_by_ess),
        p_discharge_by_ess=dict(grid_vars.p_discharge_by_ess),
        e_batt_by_ess=dict(grid_vars.e_batt_by_ess),
        battery_params_by_id=dict(grid_vars.battery_params_by_id),
        p_pv_curtail=list(grid_vars.p_pv_curtail),
        relaxed_soc_bounds_percent=relaxed_soc_bounds or None,
        reserve_floor_kwh=reserve_floor[0] if reserve_floor else None,
        reserve_start_kwh=reserve_floor[1] if reserve_floor else None,
        plant_start_energy_kwh=sum(
            _initial_energy_by_ess(grid_vars, current_soc, current_soc_by_id).values()
        ),
    )

