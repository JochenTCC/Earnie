"""Physical standby_backup powerstation planning (2.7.h).

Virtual floors are intentionally unsupported (savings study / backlog go/no-go).
"""
from __future__ import annotations

import logging
from typing import Any

import pulp

from house_config.powerstation import (
    BACKING_PHYSICAL,
    BACKING_VIRTUAL,
    ROLE_STANDBY_BACKUP,
    is_powerstation,
    normalize_attached_consumer_ids,
)
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h

logger = logging.getLogger(__name__)

SOURCE_GRID = 0
SOURCE_BATTERY = 1


def _appliance_continuous_kw(app: dict | None) -> float:
    """Resolve continuous kW from appliance or consumer-shaped dict."""
    if not isinstance(app, dict):
        return 0.0
    raw = app.get("default_power_kw")
    if raw is None:
        rec = app.get("appliance_recommendation")
        if isinstance(rec, dict) and rec.get("default_power_kw") is not None:
            raw = rec.get("default_power_kw")
    if raw is None:
        raw = app.get("nominal_power_kw")
    try:
        return max(0.0, float(raw or 0.0))
    except (TypeError, ValueError):
        return 0.0


def attached_load_kw(ps: dict, appliances_by_id: dict[str, dict] | None = None) -> float:
    """Continuous load kW = sum of attached consumers' default_power_kw."""
    apps = appliances_by_id or {}
    ids = normalize_attached_consumer_ids(ps)
    total = 0.0
    for cid in ids:
        total += _appliance_continuous_kw(apps.get(cid))
    if total > 0.0:
        return total
    if ids:
        # Attached ids present but no usable power — do not invent a sizing load.
        logger.warning(
            "standby attached consumers %s have no default/nominal power_kw; load_kw=0",
            ids,
        )
        return 0.0
    # No attached consumers: sizing hint from pack charge power.
    return max(0.05, float(ps.get("battery_max_charge_power_kw") or 0.15) * 0.25)


def reserve_target_kwh_for_standby(
    *,
    load_kw: float,
    expensive_hours: float,
    capacity_kwh: float,
) -> float:
    """Reserve sizing: power × expensive hours, capped by pack capacity."""
    raw = max(0.0, float(load_kw)) * max(0.0, float(expensive_hours))
    cap = max(0.0, float(capacity_kwh))
    if cap > 0.0:
        return min(raw, cap)
    return raw


def _hk_limits_from_powerstation(ps: dict) -> dict[str, Any]:
    """Optimizer-shaped limit fields + ``limits_from_live`` for resolve."""
    return {
        "id": str(ps.get("id") or "").strip(),
        "max_charge_power_kw": float(
            ps.get("battery_max_charge_power_kw")
            or ps.get("max_charge_power_kw")
            or 0.0
        ),
        "max_discharge_power_kw": float(
            ps.get("battery_max_discharge_power_kw")
            or ps.get("max_discharge_power_kw")
            or 0.0
        ),
        "min_soc": float(ps.get("battery_min_soc") or ps.get("min_soc") or 0.0),
        "max_soc": float(ps.get("battery_max_soc") or ps.get("max_soc") or 100.0),
        "limits_from_live": bool(ps.get("limits_from_live", False)),
    }


def collect_standby_packs(
    *,
    powerstations: list[dict] | dict[str, dict],
    appliances: list[dict] | None = None,
    telemetry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Physical ``role: standby_backup`` packs only; virtual is skipped.

    Charge/SOC caps use the same HK ∩ live resolve as house ESS (2.7.j).
    """
    from settings.ess_limits_resolve import apply_effective_ess_limits

    if isinstance(powerstations, dict):
        items = list(powerstations.values())
    else:
        items = list(powerstations or [])
    apps_by_id = {
        str(a.get("id") or "").strip(): a
        for a in (appliances or [])
        if isinstance(a, dict) and str(a.get("id") or "").strip()
    }
    out: list[dict[str, Any]] = []
    for ps in items:
        if not isinstance(ps, dict) or not is_powerstation(ps):
            continue
        role = str(ps.get("role") or "").strip().lower()
        if role != ROLE_STANDBY_BACKUP:
            continue
        backing = str(ps.get("backing") or BACKING_VIRTUAL).strip().lower()
        ps_id = str(ps.get("id") or "").strip()
        if not ps_id:
            continue
        if backing != BACKING_PHYSICAL:
            logger.info(
                "skip virtual standby_backup powerstation '%s' "
                "(physical only; raise house min_soc instead).",
                ps_id,
            )
            continue
        load_kw = attached_load_kw(ps, apps_by_id)
        hk = _hk_limits_from_powerstation(ps)
        # Powerstations: only entity-scoped live gets (never plant-flat house values).
        from ehal.ess_fields import ess_field

        scoped: dict[str, Any] | None = None
        if isinstance(telemetry, dict):
            sliced = {
                kind: telemetry[ess_field(ps_id, kind)]
                for kind in (
                    "get_ess_soc_min",
                    "get_ess_soc_max",
                    "get_ess_max_charge_power",
                    "get_ess_max_discharge_power",
                )
                if ess_field(ps_id, kind) in telemetry
            }
            scoped = sliced or None
        effective = apply_effective_ess_limits(hk, telemetry=scoped)
        out.append(
            {
                "powerstation_id": ps_id,
                "backing": BACKING_PHYSICAL,
                "role": ROLE_STANDBY_BACKUP,
                "load_kw": load_kw,
                "capacity_kwh": float(ps.get("battery_capacity_kwh") or 0.0),
                "max_charge_power_kw": float(effective["max_charge_power_kw"]),
                "min_soc": float(effective["min_soc"]),
                "max_soc": float(effective["max_soc"]),
                "efficiency": float(ps.get("battery_efficiency") or ps.get("efficiency") or 0.95),
                "attached_consumer_ids": normalize_attached_consumer_ids(ps),
                "battery": ps,
            }
        )
    return out


def _slot_price_buy(row: dict[str, Any]) -> float:
    for key in ("k_act", "price_buy", "price", "market_price"):
        if key in row and row[key] is not None:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                continue
    return 0.0


def plan_standby_horizon(
    matrix: list[dict[str, Any]],
    packs: list[dict[str, Any]],
    *,
    current_soc_by_id: dict[str, float] | None = None,
    dt_h: float = DEFAULT_DT_H,
) -> dict[str, dict[str, Any]]:
    """Per pack: MILP binary island schedule + charge kW series.

    Returns ``{ps_id: {source_select: list[int], charge_kw: list[float], …}}``.
    """
    validate_dt_h(dt_h)
    horizon = len(matrix)
    if horizon < 1 or not packs:
        return {}
    soc_map = current_soc_by_id or {}
    plans: dict[str, dict[str, Any]] = {}
    for pack in packs:
        ps_id = str(pack["powerstation_id"])
        if ps_id not in soc_map:
            logger.warning(
                "skip standby plan for %s — no own SoC (refuse fallback)",
                ps_id,
            )
            continue
        plan = _solve_one_pack(
            matrix,
            pack,
            current_soc=float(soc_map[ps_id]),
            dt_h=dt_h,
        )
        if plan is not None:
            plans[ps_id] = plan
    return plans


def _solve_one_pack(
    matrix: list[dict[str, Any]],
    pack: dict[str, Any],
    *,
    current_soc: float,
    dt_h: float,
) -> dict[str, Any] | None:
    horizon = len(matrix)
    load_kw = max(0.0, float(pack["load_kw"]))
    capacity = max(0.0, float(pack["capacity_kwh"]))
    max_charge = max(0.0, float(pack["max_charge_power_kw"]))
    min_soc = float(pack["min_soc"])
    max_soc = float(pack["max_soc"])
    eta = max(0.05, min(1.0, float(pack["efficiency"])))
    if capacity <= 1e-9 or load_kw <= 1e-9:
        return _grid_only_plan(horizon, load_kw)

    e_min = (min_soc / 100.0) * capacity
    e_max = (max_soc / 100.0) * capacity
    e0 = max(e_min, min(e_max, (current_soc / 100.0) * capacity))

    prob, island, p_charge = _build_standby_problem(
        matrix,
        str(pack["powerstation_id"]),
        load_kw=load_kw,
        max_charge=max_charge,
        eta=eta,
        energy_bounds=(e_min, e_max, e0),
        dt_h=dt_h,
    )

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] not in ("Optimal", "Not Solved"):
        logger.warning(
            "standby MILP failed for %s: %s",
            pack["powerstation_id"],
            pulp.LpStatus[status],
        )
        return _grid_only_plan(horizon, load_kw)

    source = [
        SOURCE_BATTERY if pulp.value(island[t]) and pulp.value(island[t]) > 0.5 else SOURCE_GRID
        for t in range(horizon)
    ]
    charge = [float(pulp.value(p_charge[t]) or 0.0) for t in range(horizon)]
    expensive_h = sum(1 for s in source if s == SOURCE_BATTERY) * dt_h
    return {
        "source_select": source,
        "charge_kw": charge,
        "load_kw": load_kw,
        "reserve_target_kwh": reserve_target_kwh_for_standby(
            load_kw=load_kw,
            expensive_hours=expensive_h,
            capacity_kwh=capacity,
        ),
    }


def _grid_only_plan(horizon: int, load_kw: float) -> dict[str, Any]:
    """Plan without islanding or charging (grid pass-through for every slot)."""
    return {
        "source_select": [SOURCE_GRID] * horizon,
        "charge_kw": [0.0] * horizon,
        "load_kw": load_kw,
    }


def _build_standby_problem(
    matrix: list[dict[str, Any]],
    ps_id: str,
    *,
    load_kw: float,
    max_charge: float,
    eta: float,
    energy_bounds: tuple[float, float, float],
    dt_h: float,
):
    """Standby MILP; returns ``(problem, island_vars, charge_vars)``."""
    horizon = len(matrix)
    e_min, e_max, e0 = energy_bounds
    prob = pulp.LpProblem(f"standby_{ps_id}", pulp.LpMinimize)
    island = [
        pulp.LpVariable(f"island_{t}", cat=pulp.LpBinary) for t in range(horizon)
    ]
    p_charge = [
        pulp.LpVariable(f"chg_{t}", lowBound=0, upBound=max_charge) for t in range(horizon)
    ]
    e_batt = [
        pulp.LpVariable(f"e_{t}", lowBound=e_min, upBound=e_max) for t in range(horizon)
    ]
    prices = [_slot_price_buy(matrix[t]) for t in range(horizon)]

    for t in range(horizon):
        # Charge only in grid pass-through; discharge = load when island.
        prob += p_charge[t] <= max_charge * (1 - island[t])
        prev = e0 if t == 0 else e_batt[t - 1]
        discharge = load_kw * island[t]
        prob += e_batt[t] == prev + (p_charge[t] * eta - discharge / eta) * dt_h

    # Cost: grid energy for attached load when not islanding + charging energy.
    # Prefer islanding expensive slots (high price × load when island=0).
    prob += pulp.lpSum(
        prices[t] * load_kw * (1 - island[t]) * dt_h
        + prices[t] * p_charge[t] * dt_h
        for t in range(horizon)
    )
    return prob, island, p_charge


def apply_standby_load_relief(
    matrix: list[dict[str, Any]],
    plans: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Adjust house ``expected_p_act`` for standby island/charge (copy).

    - Island (battery source): subtract attached ``load_kw`` (served by the pack).
    - Grid pass-through with planned ``charge_kw``: add that charge so the house
      MILP covers it from grid buy and/or house-battery discharge.
    """
    if not plans or not matrix:
        return matrix
    out = [dict(row) for row in matrix]
    for t, row in enumerate(out):
        if "expected_p_act" not in row:
            continue
        relief = 0.0
        charge_kw = 0.0
        for plan in plans.values():
            selects = plan.get("source_select") or []
            charges = plan.get("charge_kw") or []
            if t < len(selects) and int(selects[t]) == SOURCE_BATTERY:
                relief += float(plan.get("load_kw") or 0.0)
            if (
                t < len(selects)
                and int(selects[t]) == SOURCE_GRID
                and t < len(charges)
            ):
                charge_kw += max(0.0, float(charges[t] or 0.0))
        p_act = float(row["expected_p_act"] or 0.0)
        if relief > 0.0:
            p_act = max(0.0, p_act - relief)
        if charge_kw > 0.0:
            p_act = p_act + charge_kw
        row["expected_p_act"] = p_act
    return out


def live_source_and_charge(
    plans: dict[str, dict[str, Any]],
    *,
    slot: int = 0,
) -> tuple[dict[str, int], dict[str, float]]:
    """Current-slot source_select and charge kW per powerstation id."""
    sources: dict[str, int] = {}
    charges: dict[str, float] = {}
    for ps_id, plan in plans.items():
        selects = plan.get("source_select") or []
        chg = plan.get("charge_kw") or []
        if slot < len(selects):
            sources[ps_id] = int(selects[slot])
        if slot < len(chg):
            # Only charge in grid pass-through
            if sources.get(ps_id, SOURCE_GRID) == SOURCE_GRID:
                charges[ps_id] = max(0.0, float(chg[slot]))
            else:
                charges[ps_id] = 0.0
    return sources, charges


def advance_physical_standby_soc_after_slot(
    soc_by_ess: dict[str, float],
    *,
    plans: dict[str, dict[str, Any]],
    packs_by_id: dict[str, dict[str, Any]],
    slot_index: int,
    dt_h: float,
) -> None:
    """Advance Chart1 physical standby SoC one slot from the standby plan.

    Energy balance mirrors ``_solve_one_pack``:
    ``E[t] = E[t-1] + (charge·η − discharge/η)·dt`` with discharge = load when island.
    """
    validate_dt_h(dt_h)
    if not plans or not soc_by_ess:
        return
    for ps_id, plan in plans.items():
        if ps_id not in soc_by_ess:
            continue
        pack = packs_by_id.get(ps_id) or {}
        capacity = max(0.0, float(pack.get("capacity_kwh") or 0.0))
        if capacity <= 1e-9:
            continue
        eta = max(0.05, min(1.0, float(pack.get("efficiency") or 0.95)))
        min_soc = float(pack.get("min_soc") or 0.0)
        max_soc = float(pack.get("max_soc") or 100.0)
        e_min = (min_soc / 100.0) * capacity
        e_max = (max_soc / 100.0) * capacity
        selects = plan.get("source_select") or []
        charges = plan.get("charge_kw") or []
        if slot_index >= len(selects):
            continue
        island = int(selects[slot_index]) == SOURCE_BATTERY
        load_kw = max(0.0, float(plan.get("load_kw") or 0.0))
        if island:
            charge_kw = 0.0
            discharge_kw = load_kw
        else:
            charge_kw = (
                max(0.0, float(charges[slot_index]))
                if slot_index < len(charges)
                else 0.0
            )
            discharge_kw = 0.0
        energy = max(e_min, min(e_max, (float(soc_by_ess[ps_id]) / 100.0) * capacity))
        energy = energy + (charge_kw * eta - discharge_kw / eta) * float(dt_h)
        energy = max(e_min, min(e_max, energy))
        soc_by_ess[ps_id] = (energy / capacity) * 100.0
