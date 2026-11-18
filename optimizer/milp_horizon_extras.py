"""Terminal / reserve / sunrise constraints and objective of the horizon MILP (split from milp_horizon)."""
from __future__ import annotations

import logging
import math
import os
from typing import Any
import pulp
from data.feed_in_prices import k_push_act_for_matrix_row
from .milp_horizon_types import MilpHorizonModel
from .slot_duration import validate_dt_h

logger = logging.getLogger(__name__)

LOOKAHEAD_ENV = "EARNIE_SE_LOOKAHEAD_H"
DEFAULT_LOOKAHEAD_H = 8.0
"""SE: hours the plan looks past SA₂ (decided 2026-11-09). The study sets the variable, 0 turns it off."""
BASE_LEVEL_ENV = "EARNIE_BASE_LEVEL"
# First-prototype assumptions, to be replaced by the empirical rule of the backlog item.
BASE_LEVEL_DAY_PER_LOOKAHEAD = 1.5
BASE_LEVEL_RESERVE_SHARE = 0.1
BASE_LEVEL_MAX_SHARE = 0.5
BASE_LEVEL_VALUE_SHARE = 0.9


def base_level_enabled() -> bool:
    """Whether the SoC base level prototype is on (``EARNIE_BASE_LEVEL`` set, off by default)."""
    return bool(os.environ.get(BASE_LEVEL_ENV, "").strip())


def lookahead_hours() -> float:
    """SE look-ahead past SA₂: ``DEFAULT_LOOKAHEAD_H`` unless ``EARNIE_SE_LOOKAHEAD_H`` is set."""
    raw = os.environ.get(LOOKAHEAD_ENV, "").strip()
    if not raw:
        return DEFAULT_LOOKAHEAD_H
    hours = float(raw)
    if hours < 0.0:
        raise ValueError(f"{LOOKAHEAD_ENV} muss >= 0 sein, gefunden {raw!r}.")
    return hours


def _plant_energy_series(model: MilpHorizonModel) -> list[list]:
    """Energy variables of every house battery in the model (one list per battery)."""
    if not model.ess_ids or not model.e_batt_by_ess:
        raise ValueError("MILP-Modell ohne Speicher-Variablen je ESS (e_batt_by_ess fehlt).")
    return [model.e_batt_by_ess[eid] for eid in model.ess_ids]


def plant_capacity_kwh(model: MilpHorizonModel) -> float:
    """Summed capacity [kWh] of the house batteries in the model: the base of the SoC anchors."""
    if not model.ess_ids or not model.battery_params_by_id:
        raise ValueError("MILP-Modell ohne Speicher-Parameter je ESS (battery_params_by_id fehlt).")
    return sum(
        float(model.battery_params_by_id[eid].get("battery_capacity_kwh") or 0.0)
        for eid in model.ess_ids
    )


def _plant_energy_at(model: MilpHorizonModel, slot_index: int):
    """Energy [kWh] stored in all house batteries at the end of ``slot_index``.

    The SoC anchors (terminal, hold) bind this sum: the callers' targets are plant SoC values
    (``plant_start_soc``, the SE carry-in chain), so a single battery must not be pinned to them.
    With one battery the sum is ``model.e_batt[slot_index]``.
    """
    return pulp.lpSum(series[slot_index] for series in _plant_energy_series(model))


def _add_terminal_soc_constraint(model: MilpHorizonModel, e_terminal: float) -> None:
    """Energy of all house batteries at the horizon end = target (anchor at simulation start)."""
    if model.horizon < 1:
        return
    model.prob += _plant_energy_at(model, model.horizon - 1) == e_terminal


def _add_soc_equality_constraint(
    model: MilpHorizonModel,
    slot_index: int,
    e_kwh: float,
) -> None:
    """Energy of all house batteries at the end of slot_index equals e_kwh (SE SA₁ carry-in)."""
    if model.horizon < 1:
        return
    if slot_index < 0 or slot_index >= model.horizon:
        raise ValueError(
            f"soc equality index {slot_index} liegt außerhalb des Horizonts "
            f"(0..{model.horizon - 1})."
        )
    model.prob += _plant_energy_at(model, slot_index) == e_kwh


def _add_virtual_reserve_asap_charge(
    model: MilpHorizonModel,
    *,
    asap_charge_kwh: float,
    max_charge_kw: float,
    efficiency: float,
) -> None:
    """Deprecated alias — prefer ``_add_virtual_reserve_deadline_charge`` (2.7.p).

    Charges the refill as soon as possible (first slots that can deliver it).
    """
    _add_virtual_reserve_charge_in_slots(
        model,
        refill_kwh=asap_charge_kwh,
        max_charge_kw=max_charge_kw,
        efficiency=efficiency,
        slots=None,
    )


def _asap_slots(model: MilpHorizonModel, ac_kwh_needed: float, max_charge_kw: float) -> list[int]:
    """Fewest leading slots whose full charge power covers ``ac_kwh_needed`` (whole horizon max)."""
    per_slot = max_charge_kw * model.dt_h
    count = math.ceil(ac_kwh_needed / per_slot - 1e-9)
    return list(range(max(1, min(model.horizon, count))))


def _add_virtual_reserve_charge_in_slots(
    model: MilpHorizonModel,
    *,
    refill_kwh: float,
    max_charge_kw: float,
    efficiency: float,
    slots: list[int] | None,
) -> None:
    """Primary ESS charge of the refill inside ``slots``; ``None`` = as soon as possible.

    When ``slots`` cannot deliver the refill at ``max_charge_kw``, the window charges what it
    can and the rest is required in the slots right after it (as soon as possible, decided
    2026-11-18), with a warning. Only an amount beyond the horizon end stays unplanned (warning;
    the next re-plan carries it). The requirement is never lowered silently.
    """
    if refill_kwh <= 1e-9 or max_charge_kw <= 1e-9 or model.horizon < 1:
        return
    eta = float(efficiency) if efficiency > 1e-9 else 1.0
    ac_kwh_needed = refill_kwh / eta
    eligible = slots if slots is not None else _asap_slots(model, ac_kwh_needed, max_charge_kw)
    per_slot = max_charge_kw * model.dt_h
    deliverable = per_slot * len(eligible)
    if ac_kwh_needed <= deliverable + 1e-9:
        model.prob += (
            pulp.lpSum(model.p_charge[t] * model.dt_h for t in eligible) >= ac_kwh_needed
        ), "virtual_reserve_deadline_charge"
        return
    if deliverable > 1e-9:
        model.prob += (
            pulp.lpSum(model.p_charge[t] * model.dt_h for t in eligible) >= deliverable
        ), "virtual_reserve_deadline_charge"
    shortfall = ac_kwh_needed - deliverable
    first_after = max(eligible) + 1 if eligible else 0
    after_count = math.ceil(shortfall / per_slot - 1e-9)
    after = list(range(first_after, min(model.horizon, first_after + after_count)))
    plannable = min(ac_kwh_needed, deliverable + per_slot * len(after))
    beyond_horizon = ac_kwh_needed - plannable
    if after:
        model.prob += (
            pulp.lpSum(model.p_charge[t] * model.dt_h for t in [*eligible, *after]) >= plannable
        ), "virtual_reserve_after_deadline_charge"
    logger.warning(
        "Virtuelle Reserve: Nachlade-Fenster (%d Slots, %.3f kW) schafft nur %.3f von "
        "%.3f kWh AC – Rest %.3f kWh in %d Slots direkt danach, %.3f kWh jenseits des "
        "Planungshorizonts.",
        len(eligible),
        float(max_charge_kw),
        deliverable,
        ac_kwh_needed,
        shortfall - beyond_horizon,
        len(after),
        beyond_horizon,
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

    Sum of ``p_charge`` over the slots that end by the deadline (all of them when the
    deadline lies beyond the horizon) must cover the AC kWh needed; the cost objective picks
    cheap slots inside that window. A slot counts only when it *ends* at or before the
    deadline (exact slot start + ``dt_h``, never floored to the hour), so no refill is planned
    after the deadline with quarter-hour slots or an unaligned deadline. A deadline before
    the end of the first slot is overdue: the refill goes into the first slots that can
    deliver it (as soon as possible, decided 2026-11-18), with a warning. A missing deadline
    or matrix, a naive deadline or a row without a tz-aware ``slot_datetime`` is an error.
    """
    if refill_kwh <= 1e-9 or max_charge_kw <= 1e-9 or model.horizon < 1:
        return
    if deadline is None:
        raise ValueError(
            "Virtuelle Reserve: Nachlademenge ohne Nachlade-Deadline "
            "(_virtual_reserve_refill_deadline_utc fehlt)."
        )
    if deadline.tzinfo is None:
        raise ValueError(
            "Virtuelle Reserve: Nachlade-Deadline ohne Zeitzone "
            f"({deadline.isoformat()})."
        )
    if not matrix:
        raise ValueError("Virtuelle Reserve: Nachlade-Deadline braucht die Planungsmatrix.")
    from datetime import timedelta

    slot_length = timedelta(hours=model.dt_h)
    eligible = [
        t
        for t in range(min(model.horizon, len(matrix)))
        if _exact_slot_start(matrix, t) + slot_length <= deadline
    ]
    if not eligible:
        logger.warning(
            "Virtuelle Reserve: Nachlade-Deadline %s ist abgelaufen (vor Ende des ersten "
            "Slots) – Nachladung (%.3f kWh) so früh wie möglich.",
            deadline.isoformat(),
            float(refill_kwh),
        )
    _add_virtual_reserve_charge_in_slots(
        model,
        refill_kwh=refill_kwh,
        max_charge_kw=max_charge_kw,
        efficiency=efficiency,
        slots=eligible or None,
    )


def _exact_slot_start(matrix: list, index: int):
    """Exact tz-aware start of matrix slot ``index`` (not floored, unlike ``matrix_slot_datetime``).

    The reserve deadline window needs the real quarter-hour start; a row without a tz-aware
    ``slot_datetime`` cannot be placed against the UTC deadline and fails loud.
    """
    from datetime import datetime

    slot = matrix[index].get("slot_datetime")
    if not isinstance(slot, datetime) or slot.tzinfo is None:
        raise ValueError(
            "Virtuelle Reserve: Matrix-Slot "
            f"{index} hat keinen Zeitpunkt mit Zeitzone (slot_datetime={slot!r}); "
            "Nachlade-Deadline nicht prüfbar."
        )
    return slot


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
    model: MilpHorizonModel,
    terminal_soc_percent: float | None,
) -> float | None:
    """Target energy [kWh] of all house batteries for a plant SoC in percent."""
    if terminal_soc_percent is None:
        return None
    return (terminal_soc_percent / 100.0) * plant_capacity_kwh(model)


def _add_milp_objective(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    fallback_k_push: float,
    ev_milp_params_by_id: dict[str, dict[str, float]],
    *,
    wear_cent_per_kwh: float,
    wear_cent_per_kwh_by_ess: dict[str, float] | None = None,
    base_level_start: tuple[int, float] | None = None,
) -> None:
    """Objective: energy cost, battery wear, curtailment, tie-breaks and credits.

    ``wear_cent_per_kwh`` prices the throughput of all batteries alike; ``wear_cent_per_kwh_by_ess``
    prices each battery's own throughput (``ValueError`` when both are set).
    """
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
    wear_cost = _wear_cost(model, dt_h, wear_cent_per_kwh, wear_cent_per_kwh_by_ess)
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


def _wear_cost(
    model: MilpHorizonModel,
    dt_h: float,
    wear_cent_per_kwh: float,
    wear_cent_per_kwh_by_ess: dict[str, float] | None,
):
    """Wear [ct] of the battery throughput (charge + discharge) over the horizon."""
    if wear_cent_per_kwh_by_ess is None:
        if wear_cent_per_kwh <= 0.0:
            return 0.0
        return wear_cent_per_kwh * dt_h * pulp.lpSum(
            model.p_charge[t] + model.p_discharge[t] for t in range(model.horizon)
        )
    if wear_cent_per_kwh > 0.0:
        raise ValueError("Verschleiß entweder für alle Speicher oder je Speicher angeben, nicht beides.")
    ess_ids = list(model.ess_ids or [])
    missing = [eid for eid in ess_ids if eid not in wear_cent_per_kwh_by_ess]
    if missing:
        raise ValueError(f"Verschleiß fehlt für Speicher {missing}.")
    if len(ess_ids) == 1:
        # One battery: its throughput is the aggregate (same objective as before per-ESS wear).
        return _wear_cost(model, dt_h, float(wear_cent_per_kwh_by_ess[ess_ids[0]]), None)
    wear_cost = 0.0
    for eid in ess_ids:
        cent = float(wear_cent_per_kwh_by_ess[eid])
        if cent <= 0.0:
            continue
        wear_cost += cent * dt_h * pulp.lpSum(
            model.p_charge_by_ess[eid][t] + model.p_discharge_by_ess[eid][t]
            for t in range(model.horizon)
        )
    return wear_cost


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
    """Energy [kWh] in the house batteries at ``last_slot`` that did not come from the grid since ``start``.

    It grows by what PV can charge beyond the load into any house battery (each with its own
    efficiency) and falls with the plant energy (``_plant_energy_at``), so a discharge takes grid
    energy first. Energy at ``start`` counts in full, its origin is not known.
    """
    first_slot, energy = start
    ess_ids = list(model.ess_ids)
    single = len(ess_ids) == 1
    efficiency_by_ess = {
        eid: float(model.battery_params_by_id[eid].get("efficiency") or 1.0) for eid in ess_ids
    }
    dt_h = float(model.dt_h)
    for t in range(first_slot, last_slot + 1):
        spare_kw = max(
            0.0, float(matrix[t].get("expected_p_pv") or 0.0) - float(matrix[t]["expected_p_act"])
        )
        pv_gain = 0.0
        pv_charges = []
        for eid in ess_ids:
            tag = f"{t}" if single else f"{eid.replace('-', '_')}_{t}"
            pv_charge = pulp.LpVariable(f"base_level_pv_charge_{tag}", lowBound=0.0, upBound=spare_kw)
            model.prob += (
                pv_charge <= model.p_charge_by_ess[eid][t],
                f"base_level_pv_charge_link_{tag}",
            )
            pv_charges.append(pv_charge)
            pv_gain += pv_charge * efficiency_by_ess[eid]
        if not single:
            model.prob += pulp.lpSum(pv_charges) <= spare_kw, f"base_level_pv_spare_{t}"
        kept = pulp.LpVariable(f"base_level_pv_kwh_{t}", lowBound=0.0)
        model.prob += kept <= energy + pv_gain * dt_h, f"base_level_pv_gain_{t}"
        model.prob += kept <= _plant_energy_at(model, t), f"base_level_pv_soc_{t}"
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
    it (``_base_level_pv_energy``). ``start`` is the first tracked slot and the plant energy
    before it (``optimizer.milp._base_level_start``). Target, held energy and PV energy are those
    of all house batteries together, like the SoC anchors.
    """
    if not base_level_enabled():
        return 0.0
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
    model.prob += held <= _plant_energy_at(model, sunrise), "base_level_held"
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
