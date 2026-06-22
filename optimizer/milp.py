"""MILP-Optimierung für Batterie und flexible Verbraucher."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pulp

import config
from .charging_context import (
    apply_charging_window_constraints,
    charging_schedule_enabled,
    consumer_charging_eligible_indices,
)
from . import battery as bat

EMPTY_MILP_PLAN = {
    "p_grid_buy": 0.0,
    "p_grid_sell": 0.0,
    "p_charge": 0.0,
    "p_discharge": 0.0,
}

_AUTOMATIK_FALLBACK = (0, 0.0, 99.0, {}, EMPTY_MILP_PLAN)


@dataclass
class MilpHorizonModel:
    prob: pulp.LpProblem
    horizon: int
    p_grid_buy: list
    p_grid_sell: list
    p_charge: list
    p_discharge: list
    e_batt: list
    consumer_on: dict[str, list]
    planned_consumers: list


def _day_indices(matrix: list[dict[str, Any]], horizon: int) -> list[int]:
    """Stunden im Planungshorizont, die zum selben Kalendertag wie t=0 gehören."""
    ref_date = matrix[0].get("date")
    if ref_date is None:
        return list(range(horizon))
    return [t for t in range(horizon) if matrix[t].get("date") == ref_date]


def _active_consumers(consumers: list | None) -> list:
    if consumers is not None:
        return consumers
    return config.get_flexible_consumers(optimizer_only=True)


def _remaining_kwh_by_consumer(
    active: list,
    consumer_remaining_kwh: dict[str, float] | None,
    spa_remaining_kwh: float | None,
) -> dict[str, float]:
    remaining: dict[str, float] = {}
    for consumer in active:
        cid = consumer["id"]
        if consumer_remaining_kwh and cid in consumer_remaining_kwh:
            remaining[cid] = max(0.0, float(consumer_remaining_kwh[cid]))
        else:
            remaining[cid] = float(consumer["daily_target_kwh"])
    if spa_remaining_kwh is not None and "swimspa" in remaining:
        remaining["swimspa"] = max(0.0, float(spa_remaining_kwh))
    return remaining


def add_min_on_time_constraints(
    prob: pulp.LpProblem,
    on_vars: list,
    min_on_quarterhours: int,
    prefix: str,
) -> None:
    """Erzwingt Mindest-Einschaltdauer; MILP arbeitet stündlich (4 Viertelstunden = 1 Slot)."""
    min_hours = max(1, (int(min_on_quarterhours) + 3) // 4)
    if min_hours <= 1:
        return
    horizon = len(on_vars)
    for t in range(horizon - min_hours + 1):
        prev = 0 if t == 0 else on_vars[t - 1]
        prob += pulp.lpSum(on_vars[t:t + min_hours]) >= min_hours * (on_vars[t] - prev)


def filter_feasible_consumers(
    consumers: list,
    remaining_kwh: dict[str, float],
    matrix: list,
    schedule_indices: list[int],
    verbose: bool,
    charging_contexts: dict[str, dict] | None,
) -> list:
    """Entfernt Verbraucher, deren Ziel im verbleibenden Horizont nicht erreichbar ist."""
    feasible = []
    contexts = charging_contexts or {}
    for consumer in consumers:
        cid = consumer["id"]
        target = remaining_kwh.get(cid, 0.0)
        if target <= 0:
            continue
        ctx = contexts.get(cid)
        if ctx is not None and not ctx.get("active", True):
            continue
        eligible = consumer_charging_eligible_indices(
            matrix, consumer, schedule_indices, ctx
        )
        capacity_indices = eligible if eligible else schedule_indices
        max_deliverable = len(capacity_indices) * consumer["nominal_power_kw"]
        if target > max_deliverable + 1e-6:
            if verbose:
                sched_hint = ""
                if charging_schedule_enabled(consumer):
                    sched_hint = f" ({len(eligible)} h im Ladezeitfenster)"
                print(
                    f"⚠️ {consumer['name']}: Ziel ({target:.2f} kWh) nicht erreichbar "
                    f"mit {len(capacity_indices)} h à {consumer['nominal_power_kw']:.2f} kW"
                    f"{sched_hint}. Wird übersprungen."
                )
            continue
        feasible.append(consumer)
    return feasible


def _build_milp_model(
    matrix: list[dict[str, Any]],
    horizon: int,
    battery_params: dict,
    current_soc: float,
    planned_consumers: list,
) -> MilpHorizonModel:
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    efficiency = battery_params["efficiency"]
    e_min = (min_soc / 100.0) * battery_capacity
    e_max = (max_soc / 100.0) * battery_capacity
    e_init = (current_soc / 100.0) * battery_capacity

    prob = pulp.LpProblem("Energy_Cost_Minimization", pulp.LpMinimize)
    p_grid_buy = [pulp.LpVariable(f"p_grid_buy_{t}", lowBound=0) for t in range(horizon)]
    p_grid_sell = [pulp.LpVariable(f"p_grid_sell_{t}", lowBound=0) for t in range(horizon)]
    p_charge = [
        pulp.LpVariable(f"p_charge_{t}", lowBound=0, upBound=max_power)
        for t in range(horizon)
    ]
    p_discharge = [
        pulp.LpVariable(f"p_discharge_{t}", lowBound=0, upBound=max_power)
        for t in range(horizon)
    ]
    e_batt = [
        pulp.LpVariable(f"e_batt_{t}", lowBound=e_min, upBound=e_max)
        for t in range(horizon)
    ]
    delta_charge = [pulp.LpVariable(f"delta_charge_{t}", cat=pulp.LpBinary) for t in range(horizon)]
    max_flex_power = sum(c["nominal_power_kw"] for c in planned_consumers)
    max_load = max((row["expected_p_act"] for row in matrix[:horizon]), default=0.0)
    max_pv = max((row["expected_p_pv"] for row in matrix[:horizon]), default=0.0)
    big_m_grid = max(max_load + max_flex_power + max_power, max_pv + max_power, 50.0)
    delta_import = [pulp.LpVariable(f"delta_import_{t}", cat=pulp.LpBinary) for t in range(horizon)]

    consumer_on: dict[str, list] = {}
    for consumer in planned_consumers:
        cid = consumer["id"]
        consumer_on[cid] = [
            pulp.LpVariable(f"{cid}_on_{t}", cat=pulp.LpBinary)
            for t in range(horizon)
        ]
        add_min_on_time_constraints(
            prob,
            consumer_on[cid],
            consumer["min_on_quarterhours"],
            cid,
        )

    for t in range(horizon):
        p_pv = matrix[t]["expected_p_pv"]
        p_con = matrix[t]["expected_p_act"]
        p_flex = pulp.lpSum(
            consumer["nominal_power_kw"] * consumer_on[consumer["id"]][t]
            for consumer in planned_consumers
        )
        prob += (
            p_pv + p_grid_buy[t] + p_discharge[t]
            == p_con + p_flex + p_grid_sell[t] + p_charge[t]
        )
        prob += p_grid_buy[t] <= big_m_grid * delta_import[t]
        prob += p_grid_sell[t] <= big_m_grid * (1 - delta_import[t])
        prob += p_charge[t] <= max_power * delta_charge[t]
        prob += p_discharge[t] <= max_power * (1 - delta_charge[t])
        if t == 0:
            prob += (
                e_batt[t]
                == e_init + p_charge[t] * efficiency - p_discharge[t] / efficiency
            )
        else:
            prob += (
                e_batt[t]
                == e_batt[t - 1] + p_charge[t] * efficiency - p_discharge[t] / efficiency
            )

    return MilpHorizonModel(
        prob=prob,
        horizon=horizon,
        p_grid_buy=p_grid_buy,
        p_grid_sell=p_grid_sell,
        p_charge=p_charge,
        p_discharge=p_discharge,
        e_batt=e_batt,
        consumer_on=consumer_on,
        planned_consumers=planned_consumers,
    )


def _add_milp_objective(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    k_push: float,
) -> None:
    model.prob += pulp.lpSum([
        model.p_grid_buy[t] * matrix[t]["k_act"] - model.p_grid_sell[t] * k_push
        for t in range(model.horizon)
    ])


def _add_consumer_delivery_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    verbose: bool,
) -> None:
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        target = remaining.get(cid, 0.0)
        if target <= 0:
            continue
        eligible = apply_charging_window_constraints(
            model.prob,
            model.consumer_on,
            matrix[: model.horizon],
            consumer,
            schedule_indices,
            charging_contexts.get(cid),
        )
        if not eligible:
            if verbose:
                print(
                    f"⚠️ {consumer['name']}: Kein zulässiges Ladezeitfenster im Horizont. "
                    "Flex-Laden wird übersprungen."
                )
            continue
        model.prob += (
            pulp.lpSum(
                consumer["nominal_power_kw"] * model.consumer_on[cid][t]
                for t in eligible
            ) >= target
        )


def _var_value_at_zero(variables: list) -> float:
    value = variables[0].varValue
    return value if value is not None else 0.0


def _extract_milp_plan(model: MilpHorizonModel) -> dict[str, float]:
    return {
        "p_grid_buy": _var_value_at_zero(model.p_grid_buy),
        "p_grid_sell": _var_value_at_zero(model.p_grid_sell),
        "p_charge": _var_value_at_zero(model.p_charge),
        "p_discharge": _var_value_at_zero(model.p_discharge),
    }


def _consumer_powers_now(model: MilpHorizonModel) -> tuple[dict[str, float], float]:
    consumer_powers: dict[str, float] = {}
    total_flex_power = 0.0
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        on_val = model.consumer_on[cid][0].varValue
        power = consumer["nominal_power_kw"] if on_val is not None and on_val > 0.5 else 0.0
        consumer_powers[cid] = power
        total_flex_power += power
    return consumer_powers, total_flex_power


def _derive_control_from_milp(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    milp_plan: dict[str, float],
    consumer_powers: dict[str, float],
    total_flex_power: float,
    current_soc: float,
    battery_params: dict,
) -> tuple[int, float, float]:
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    efficiency = battery_params["efficiency"]

    opt_charge = milp_plan["p_charge"]
    opt_discharge = milp_plan["p_discharge"]
    opt_grid_buy = milp_plan["p_grid_buy"]
    p_pv_0 = matrix[0]["expected_p_pv"]
    p_con_0 = matrix[0]["expected_p_act"]
    net_pv_surplus = p_pv_0 - p_con_0 - total_flex_power
    planned_soc = round(
        max(
            min_soc,
            min(max_soc, (model.e_batt[0].varValue / battery_capacity) * 100.0),
        ),
        1,
    )

    mode = bat.MODE_AUTOMATIK
    target_power = 0.0
    target_soc = 99.0
    threshold = bat.power_threshold_kw(max_power)

    if opt_charge > threshold and opt_grid_buy > threshold:
        mode = bat.MODE_ZWANGS_LADEN
        target_soc = round(max(current_soc, planned_soc), 1)
        target_power = bat.charge_kw_for_hourly_soc(
            current_soc,
            target_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
    elif opt_discharge > threshold:
        candidate_soc = round(min(current_soc, planned_soc), 1)
        candidate_power = bat.discharge_kw_for_hourly_soc(
            current_soc,
            candidate_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
        automatik_power = bat.automatik_discharge_kw(net_pv_surplus, max_power)
        if candidate_power > automatik_power + threshold:
            mode = bat.MODE_ZWANGS_ENTLADEN
            target_soc = candidate_soc
            target_power = candidate_power
    elif (
        net_pv_surplus < -threshold
        and opt_discharge < threshold
        and current_soc > (min_soc + 2.0)
    ):
        mode = bat.MODE_ENTLADESPERRE
        target_power = 0.0
        target_soc = 100.0

    return mode, target_power, target_soc


def _log_milp_decision(
    current_hour: int,
    matrix: list[dict[str, Any]],
    current_soc: float,
    milp_plan: dict[str, float],
    model: MilpHorizonModel,
    remaining: dict[str, float],
    consumer_powers: dict[str, float],
    mode: int,
    target_power: float,
    target_soc: float,
) -> None:
    opt_charge = milp_plan["p_charge"]
    opt_discharge = milp_plan["p_discharge"]
    opt_grid_buy = milp_plan["p_grid_buy"]
    print(f"\n--- 🧮 MILP Optimierungs-Entscheidung für {current_hour}:00 Uhr ---")
    print(f"Aktueller Brutto-Preis: {matrix[0]['k_act']:.2f} Cent/kWh")
    print(f"Aktueller Akku-SoC    : {current_soc:.1f}%")
    print(
        f"Optimierter Fahrplan  : Ladung={opt_charge:.2f} kW | "
        f"Entladung={opt_discharge:.2f} kW | Netzbezug={opt_grid_buy:.2f} kW"
    )
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        power_now = consumer_powers.get(cid, 0.0)
        planned_kwh = sum(
            consumer["nominal_power_kw"]
            for t in range(model.horizon)
            if model.consumer_on[cid][t].varValue is not None
            and model.consumer_on[cid][t].varValue > 0.5
        )
        print(
            f"{consumer['name']:<16}: Jetzt={'AN' if power_now > 0 else 'AUS'} "
            f"({power_now:.2f} kW) | Restziel={remaining.get(cid, 0.0):.2f} kWh | "
            f"Geplant={planned_kwh:.2f} kWh | min_on={consumer['min_on_quarterhours']} x 15min"
        )
    modi_text = {
        bat.MODE_AUTOMATIK: "AUTOMATIK",
        bat.MODE_ZWANGS_LADEN: "ZWANGSLADEN",
        bat.MODE_ENTLADESPERRE: "ENTLADESPERRE",
        bat.MODE_ZWANGS_ENTLADEN: "ZWANGSENTLADEN",
    }
    print(
        f"-> Steuerbefehl Loxone: {modi_text[mode]} "
        f"(Leistung: {target_power} kW, Ziel-SoC: {target_soc}%)"
    )


def milp_optimizer(
    matrix: list[dict[str, Any]],
    current_hour: int,
    current_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    consumers: list | None = None,
    consumer_remaining_kwh: dict[str, float] | None = None,
    spa_cfg: dict | None = None,
    spa_remaining_kwh: float | None = None,
    flex_indices: list[int] | None = None,
    charging_contexts: dict[str, dict] | None = None,
) -> tuple[int, float, float, dict[str, float], dict[str, float]]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Optimiert Batterie und alle konfigurierten flexible_consumers gemeinsam per MILP.
    Rückgabe: (mode, target_power, target_soc, {consumer_id: leistung_kw}, milp_plan)
    """
    if not matrix:
        print("🚨 Optimizer-Fehler: Matrix ist leer.")
        return _AUTOMATIK_FALLBACK

    battery_params = battery_params or config.get_battery_params()
    k_push = k_push if k_push is not None else config.get_push_price_cent()
    active = _active_consumers(consumers)
    remaining = _remaining_kwh_by_consumer(active, consumer_remaining_kwh, spa_remaining_kwh)

    horizon = min(24, len(matrix))
    day_indices = _day_indices(matrix, horizon)
    schedule_indices = flex_indices if flex_indices is not None else day_indices
    contexts = charging_contexts or {}
    planned_consumers = filter_feasible_consumers(
        active,
        remaining,
        matrix[:horizon],
        schedule_indices,
        verbose,
        contexts,
    )

    model = _build_milp_model(matrix, horizon, battery_params, current_soc, planned_consumers)
    _add_milp_objective(model, matrix, k_push)
    _add_consumer_delivery_constraints(
        model,
        matrix,
        remaining,
        schedule_indices,
        contexts,
        verbose,
    )

    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[model.prob.status] != "Optimal":
        if verbose:
            print(
                f"⚠️ MILP-Solver konnte keine optimale Lösung finden "
                f"Status: {pulp.LpStatus[model.prob.status]}. Fallback auf Automatik."
            )
        return _AUTOMATIK_FALLBACK

    milp_plan = _extract_milp_plan(model)
    consumer_powers, total_flex_power = _consumer_powers_now(model)
    mode, target_power, target_soc = _derive_control_from_milp(
        model,
        matrix,
        milp_plan,
        consumer_powers,
        total_flex_power,
        current_soc,
        battery_params,
    )

    if verbose:
        _log_milp_decision(
            current_hour,
            matrix,
            current_soc,
            milp_plan,
            model,
            remaining,
            consumer_powers,
            mode,
            target_power,
            target_soc,
        )

    return mode, target_power, target_soc, consumer_powers, milp_plan
