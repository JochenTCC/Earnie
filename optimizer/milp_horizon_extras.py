"""Terminal / reserve / sunrise constraints and objective of the horizon MILP (split from milp_horizon)."""
from __future__ import annotations

import os
from typing import Any
import pulp
from data.feed_in_prices import k_push_act_for_matrix_row
from .milp_horizon_types import MilpHorizonModel
from .slot_duration import validate_dt_h

LOOKAHEAD_ENV = "EARNIE_SE_LOOKAHEAD_H"
DEFAULT_LOOKAHEAD_H = 8.0
"""SE: hours the plan looks past SA₂ (decided 2026-11-09). The study sets the variable, 0 turns it off."""
BASE_LEVEL_ENV = "EARNIE_BASE_LEVEL"
# First-prototype assumptions, to be replaced by the empirical rule of the backlog item.
BASE_LEVEL_DAY_PER_LOOKAHEAD = 1.5
BASE_LEVEL_RESERVE_SHARE = 0.1
BASE_LEVEL_MAX_SHARE = 0.5
BASE_LEVEL_VALUE_SHARE = 0.9


def lookahead_hours() -> float:
    """SE look-ahead past SA₂: ``DEFAULT_LOOKAHEAD_H`` unless ``EARNIE_SE_LOOKAHEAD_H`` is set."""
    raw = os.environ.get(LOOKAHEAD_ENV, "").strip()
    if not raw:
        return DEFAULT_LOOKAHEAD_H
    hours = float(raw)
    if hours < 0.0:
        raise ValueError(f"{LOOKAHEAD_ENV} muss >= 0 sein, gefunden {raw!r}.")
    return hours


def _add_terminal_soc_constraint(model: MilpHorizonModel, e_terminal: float) -> None:
    """End-SOC am Horizontende = Ziel-SOC (Anker zu Simulations-/Planungsbeginn)."""
    if model.horizon < 1:
        return
    model.prob += model.e_batt[model.horizon - 1] == e_terminal


def _add_soc_equality_constraint(
    model: MilpHorizonModel,
    slot_index: int,
    e_kwh: float,
) -> None:
    """SOC at slot_index equals e_kwh (sunrise floor or SE SA₁ carry-in)."""
    if model.horizon < 1:
        return
    if slot_index < 0 or slot_index >= model.horizon:
        raise ValueError(
            f"soc equality index {slot_index} liegt außerhalb des Horizonts "
            f"(0..{model.horizon - 1})."
        )
    model.prob += model.e_batt[slot_index] == e_kwh


def _add_virtual_reserve_asap_charge(
    model: MilpHorizonModel,
    *,
    asap_charge_kwh: float,
    max_charge_kw: float,
    efficiency: float,
) -> None:
    """Deprecated alias — prefer ``_add_virtual_reserve_deadline_charge`` (2.7.p)."""
    _add_virtual_reserve_deadline_charge(
        model,
        matrix=None,
        refill_kwh=asap_charge_kwh,
        max_charge_kw=max_charge_kw,
        efficiency=efficiency,
        deadline=None,
    )


def _add_virtual_reserve_deadline_charge(
    model: MilpHorizonModel,
    *,
    matrix: list | None,
    refill_kwh: float,
    max_charge_kw: float,
    efficiency: float,
    deadline,
) -> None:
    """Require primary ESS charge of refill kWh by deadline (price-optimal within window).

    Sum of ``p_charge`` over slots before the deadline (or full horizon when the
    deadline is missing / beyond the horizon) must cover AC kWh needed. The MILP
    cost objective picks cheap slots inside that window — not ASAP front-loading.
    """
    if refill_kwh <= 1e-9 or max_charge_kw <= 1e-9 or model.horizon < 1:
        return
    eta = float(efficiency) if efficiency > 1e-9 else 1.0
    ac_kwh_needed = refill_kwh / eta
    from optimizer.charging_schedule import matrix_slot_datetime

    eligible: list[int] = []
    if matrix and deadline is not None:
        for t in range(min(model.horizon, len(matrix))):
            if matrix_slot_datetime(matrix, t) < deadline:
                eligible.append(t)
    if not eligible:
        # No usable pre-deadline slots (missing deadline / past): full horizon so
        # the cost objective can still pick cheap slots inside the plan.
        eligible = list(range(model.horizon))

    deliverable = max_charge_kw * model.dt_h * len(eligible)
    required = min(ac_kwh_needed, deliverable)
    if required <= 1e-9:
        return
    model.prob += (
        pulp.lpSum(model.p_charge[t] * model.dt_h for t in eligible) >= required
    ), "virtual_reserve_deadline_charge"


def _add_sunrise_soc_min_constraint(
    model: MilpHorizonModel,
    sunrise_index: int,
    e_min_kwh: float,
) -> None:
    """
    Legacy no-op: ``e_batt`` already has lowBound=e_min every slot.

    Hard ``e_batt[sunrise] == SOC_min`` forced dumping residual evening SoC at SA₁
    (Chart jump ~20%→10%). Live uses PV-only charge through sunrise instead; SE
    SA₁ carry-in uses ``_add_soc_equality_constraint``.
    """
    del model, sunrise_index, e_min_kwh


def _add_pv_only_charge_through_sunrise(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    sunrise_index: int,
) -> None:
    """
    No grid-charged battery increase through the sunrise SOC_min slot.

    Hourly MPC otherwise charges before SA₁ for later flex, then re-opts the flex
    away and is forced to export to meet SOC_min (SoC spike at SA₁). Spec assumes
    night grid charge is economically irrelevant for this battery size.
    """
    if model.horizon < 1:
        return
    last = min(sunrise_index, model.horizon - 1)
    if last < 0:
        return
    for t in range(last + 1):
        pv_cap = max(0.0, float(matrix[t].get("expected_p_pv", 0.0) or 0.0))
        model.prob += model.p_charge[t] <= pv_cap


def _terminal_soc_energy_kwh(
    battery_params: dict,
    terminal_soc_percent: float | None,
) -> float | None:
    if terminal_soc_percent is None:
        return None
    return (terminal_soc_percent / 100.0) * battery_params["battery_capacity_kwh"]


def _add_milp_objective(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    fallback_k_push: float,
    ev_milp_params_by_id: dict[str, dict[str, float]],
    *,
    wear_cent_per_kwh: float,
    base_level_start: tuple[int, float] | None = None,
) -> None:
    dt_h = validate_dt_h(model.dt_h)
    energy_cost = pulp.lpSum([
        (
            model.p_grid_buy[t] * matrix[t]["k_act"]
            - model.p_grid_sell[t]
            * k_push_act_for_matrix_row(matrix[t], fallback_k_push)
        )
        * dt_h
        for t in range(model.horizon)
    ])
    wear_cost = 0.0
    if wear_cent_per_kwh > 0.0:
        wear_cost = wear_cent_per_kwh * dt_h * pulp.lpSum(
            model.p_charge[t] + model.p_discharge[t]
            for t in range(model.horizon)
        )
    # Prefer export over free curtail when k_push ≈ 0; still << real tariffs.
    curtail_cost = 0.0
    if model.p_pv_curtail:
        curtail_cost = 1e-4 * dt_h * pulp.lpSum(
            model.p_pv_curtail[t] for t in range(model.horizon)
        )
    tie_break = 0.0
    for cid, ev_params in (ev_milp_params_by_id or {}).items():
        if cid not in model.consumer_on:
            continue
        on_vars = model.consumer_on[cid]
        eps_on = ev_params["tie_break_on_epsilon"]
        eps_time = ev_params["tie_break_time_epsilon"]
        tie_break += eps_on * pulp.lpSum(on_vars) + eps_time * pulp.lpSum(
            t * on_vars[t] for t in range(len(on_vars))
        )
    model.prob += (
        energy_cost
        + wear_cost
        + curtail_cost
        + tie_break
        - _heating_rod_fuel_credit(model)
        - _base_level_credit(model, matrix, base_level_start)
    )


def _base_level_target_kwh(surplus_lookahead_kwh: float, e_min: float, e_max: float) -> float:
    """Night level [kWh] that still leaves room for tomorrow's expected surplus and the reserve."""
    surplus = surplus_lookahead_kwh * BASE_LEVEL_DAY_PER_LOOKAHEAD
    room = e_max - surplus - BASE_LEVEL_RESERVE_SHARE * e_max
    return max(e_min, min(room, BASE_LEVEL_MAX_SHARE * e_max))


def _base_level_pv_energy(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    last_slot: int,
    start: tuple[int, float],
):
    """Energy [kWh] in the battery at ``last_slot`` that did not come from the grid since ``start``.

    It grows by what PV can charge beyond the load and falls with the SoC, so a discharge takes
    grid energy first. Energy at ``start`` counts in full, its origin is not known.
    """
    first_slot, energy = start
    ess_id = model.ess_ids[0]
    efficiency = float(model.battery_params_by_id[ess_id].get("efficiency") or 1.0)
    dt_h = float(model.dt_h)
    for t in range(first_slot, last_slot + 1):
        spare_kw = max(
            0.0, float(matrix[t].get("expected_p_pv") or 0.0) - float(matrix[t]["expected_p_act"])
        )
        pv_charge = pulp.LpVariable(f"base_level_pv_charge_{t}", lowBound=0.0, upBound=spare_kw)
        kept = pulp.LpVariable(f"base_level_pv_kwh_{t}", lowBound=0.0)
        model.prob += pv_charge <= model.p_charge[t], f"base_level_pv_charge_link_{t}"
        model.prob += kept <= energy + pv_charge * efficiency * dt_h, f"base_level_pv_gain_{t}"
        model.prob += kept <= model.e_batt[t], f"base_level_pv_soc_{t}"
        energy = kept
    return energy


def _base_level_credit(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    start: tuple[int, float] | None,
):
    """Prototype of the SoC base level: value of the energy held at SA₂ up to the level (off by default).

    Needs the look-ahead: the slots past the book are tomorrow's first hours. The value is a bonus:
    the energy can still replace an import past SA₂, so value and use add up and a price below the
    buy price alone would not keep the grid out. Only energy that did not come from the grid earns
    it (``_base_level_pv_energy``). ``start`` is the first tracked slot and the energy before it.
    """
    if not os.environ.get(BASE_LEVEL_ENV, "").strip():
        return 0.0
    if len(model.ess_ids) != 1:
        raise ValueError(
            f"{BASE_LEVEL_ENV} kann bisher nur einen Speicher abbilden, gefunden: {model.ess_ids}."
        )
    if start is None:
        raise ValueError(f"{BASE_LEVEL_ENV} braucht den Start-SoC des Plans (base_level_start).")
    lookahead_h = lookahead_hours()
    lookahead_slots = round(lookahead_h / float(model.dt_h))
    if not 1 <= lookahead_slots < model.horizon:
        raise ValueError(
            f"{BASE_LEVEL_ENV} braucht {LOOKAHEAD_ENV} innerhalb des Horizonts "
            f"({lookahead_slots} Slots, Horizont {model.horizon})."
        )
    sunrise = model.horizon - 1 - lookahead_slots
    surplus_kwh = sum(
        max(0.0, float(matrix[t].get("expected_p_pv") or 0.0) - float(matrix[t]["expected_p_act"]))
        * float(model.dt_h)
        for t in range(sunrise + 1, model.horizon)
    )
    vars_by_ess = model.e_batt_by_ess or {}
    e_min = sum(float(values[sunrise].lowBound) for values in vars_by_ess.values())
    e_max = sum(float(values[sunrise].upBound) for values in vars_by_ess.values())
    target = _base_level_target_kwh(surplus_kwh, e_min, e_max)
    if target <= e_min:
        return 0.0
    value = max(0.0, BASE_LEVEL_VALUE_SHARE * min(float(row["k_act"]) for row in matrix[: model.horizon]))
    held = pulp.LpVariable("base_level_held_kwh", lowBound=0.0, upBound=target)
    model.prob += held <= model.e_batt[sunrise], "base_level_held"
    model.prob += held <= _base_level_pv_energy(model, matrix, sunrise, start), "base_level_from_pv"
    return value * held


def _heating_rod_fuel_credit(model: MilpHorizonModel):
    """Avoided fuel cost [cent] of heating rods beside a fuel heat source (SUSI P1)."""
    credit = 0.0
    dt_h = float(model.dt_h)
    for consumer in model.planned_consumers:
        cent = consumer.get("fuel_credit_cent_per_kwh")
        if cent is None:
            continue
        cid = consumer["id"]
        charge_kw = float(model.consumer_milp_charge_kw[cid])
        credit += float(cent) * charge_kw * dt_h * pulp.lpSum(model.consumer_on[cid])
    return credit
