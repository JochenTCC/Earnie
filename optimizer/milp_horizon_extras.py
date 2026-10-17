"""Terminal / reserve / sunrise constraints and objective of the horizon MILP (split from milp_horizon)."""
from __future__ import annotations

from typing import Any
import pulp
from data.feed_in_prices import k_push_act_for_matrix_row
from .milp_horizon_types import MilpHorizonModel
from .slot_duration import validate_dt_h


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
    model.prob += energy_cost + wear_cost + curtail_cost + tie_break
