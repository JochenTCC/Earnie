"""Price-aware floor of the virtual powerstation reserve, per slot (Reserve P2).

The reserve is held in slot ``t`` only where feeding from the battery is cheaper than the grid:

    price[t] > fill_cost(t)

``fill_cost(t)`` is the cheapest way to have the reserve in the battery at ``t``:

- from a slot ``s < t`` of the horizon: ``price[s] / eta_rt + hold(s, t)``,
- from energy already stored (the persisted fill basis, see
  ``runtime_store.powerstation_reserves``): ``basis / eta_rt + hold(basis time, t)``.

``eta_rt`` is the round trip of the battery, ``efficiency ** 2`` (the MILP applies
``efficiency`` once on charge and once on discharge). ``hold`` is the idle drain over the hold
time (``idle_drain_hold_kwh``), bought at the fill price through the charge path and spread
over the reserve's kWh. Slot 0 has no slot before it: it only pays through the fill basis.

The floor binds the stored energy at the start and the end of a paying slot. ``e_batt[k]`` is
the energy at the end of slot ``k`` (start of ``k + 1``), so it carries the reserve when slot
``k`` or slot ``k + 1`` pays. The cost objective then builds the reserve in the cheapest slots
before the first paying slot, like an EV charging deadline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .battery import idle_drain_hold_kwh, idle_drain_kw

logger = logging.getLogger(__name__)

# Keys on the primary battery params, set by ``powerstation_reserve.apply_virtual_reserve_floor``.
RESERVE_KWH_KEY = "_virtual_reserve_kwh"
FLOOR_SOC_KEY = "_virtual_reserve_floor_soc"
BASE_MIN_SOC_KEY = "_virtual_reserve_base_min_soc"
BASIS_PRICE_KEY = "_virtual_reserve_basis_price"
BASIS_AT_KEY = "_virtual_reserve_basis_at"

_EPS = 1e-9


@dataclass(frozen=True)
class ReserveFloorPlan:
    """Per-slot floor of the primary house battery (energies in kWh)."""

    base_kwh: float
    reserve_floor_kwh: float
    reserve_kwh: float
    pays: list[bool]
    # Raw import price that justifies ``pays[t]`` and when that energy is (was) bought.
    fill_price: list[float | None]
    fill_at: list[datetime | None]
    # Lower bound of the energy at the end of slot k (before the reachability cap).
    floor_kwh: list[float]

    @property
    def held_now(self) -> bool:
        """The reserve has to be in the battery at the end of slot 0."""
        return bool(self.floor_kwh) and self.floor_kwh[0] > self.base_kwh + _EPS

    def first_paying_slot(self) -> int | None:
        for t, pays in enumerate(self.pays):
            if pays:
                return t
        return None


def slot_start(matrix: list[dict[str, Any]], index: int) -> datetime:
    """Exact tz-aware start of matrix slot ``index``; a row without one fails loud."""
    slot = matrix[index].get("slot_datetime")
    if not isinstance(slot, datetime) or slot.tzinfo is None:
        raise ValueError(
            "Virtuelle Reserve: Matrix-Slot "
            f"{index} hat keinen Zeitpunkt mit Zeitzone (slot_datetime={slot!r}); "
            "Haltedauer der gespeicherten Reserve nicht bestimmbar."
        )
    return slot


def _parse_basis_at(raw: object) -> datetime:
    value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError(f"Virtuelle Reserve: Füllzeitpunkt ohne Zeitzone ({raw!r}).")
    return value


def reserve_price_floor(
    bat: dict,
    matrix: list[dict[str, Any]],
    *,
    horizon: int,
    dt_h: float,
) -> ReserveFloorPlan | None:
    """Floor per slot for the primary battery ``bat``; ``None`` without a virtual reserve."""
    reserve_kwh = float(bat.get(RESERVE_KWH_KEY) or 0.0)
    if reserve_kwh <= _EPS or FLOOR_SOC_KEY not in bat:
        return None
    if dt_h <= 0.0:
        raise ValueError(f"reserve_price_floor: dt_h must be > 0, got {dt_h}")
    if "efficiency" not in bat:
        raise ValueError("Virtuelle Reserve: Batterieparameter ohne efficiency.")
    eff = float(bat["efficiency"])
    if not 0.0 < eff <= 1.0:
        raise ValueError(f"Virtuelle Reserve: efficiency {eff!r} außerhalb (0, 1].")
    eta_rt = eff * eff
    capacity = float(bat["battery_capacity_kwh"])
    base_kwh = float(bat[BASE_MIN_SOC_KEY]) / 100.0 * capacity
    reserve_floor_kwh = float(bat[FLOOR_SOC_KEY]) / 100.0 * capacity
    horizon = min(int(horizon), len(matrix))
    prices = [float(matrix[t]["k_act"]) for t in range(horizon)]
    drain = idle_drain_kw(bat) > 0.0

    def cost(price: float, hold_h: float) -> float:
        hold = 0.0
        if drain and price > 0.0:
            hold = price / eff * idle_drain_hold_kwh(bat, max(0.0, hold_h)) / reserve_kwh
        return price / eta_rt + hold

    basis_price = bat.get(BASIS_PRICE_KEY)
    basis_at: datetime | None = None
    basis_held_h = 0.0
    if basis_price is not None and horizon > 0:
        basis_at = _parse_basis_at(bat[BASIS_AT_KEY])
        basis_held_h = max(0.0, (slot_start(matrix, 0) - basis_at).total_seconds() / 3600.0)

    pays: list[bool] = []
    fill_price: list[float | None] = []
    fill_at: list[datetime | None] = []
    for t in range(horizon):
        best_cost: float | None = None
        best_price: float | None = None
        best_at: datetime | None = None
        if basis_price is not None:
            best_cost = cost(float(basis_price), basis_held_h + t * dt_h)
            best_price, best_at = float(basis_price), basis_at
        for s in range(t):
            c = cost(prices[s], (t - s) * dt_h)
            if best_cost is None or c < best_cost - _EPS:
                best_cost, best_price = c, prices[s]
                best_at = matrix[s].get("slot_datetime")
        ok = best_cost is not None and prices[t] > best_cost + _EPS
        pays.append(ok)
        fill_price.append(best_price if ok else None)
        fill_at.append(best_at if ok else None)

    floor_kwh = [
        reserve_floor_kwh if (pays[k] or (k + 1 < horizon and pays[k + 1])) else base_kwh
        for k in range(horizon)
    ]
    return ReserveFloorPlan(
        base_kwh=base_kwh,
        reserve_floor_kwh=reserve_floor_kwh,
        reserve_kwh=reserve_kwh,
        pays=pays,
        fill_price=fill_price,
        fill_at=fill_at,
        floor_kwh=floor_kwh,
    )


def reachable_floor_kwh(
    plan: ReserveFloorPlan,
    bat: dict,
    *,
    e_init: float,
    dt_h: float,
) -> list[float]:
    """``plan.floor_kwh`` lowered where the battery cannot reach it from ``e_init``.

    Reachable by the end of slot ``k``: ``e_init`` plus ``k + 1`` slots of full charge power
    through the charge path, minus the idle drain. A floor above that is lowered to it (never
    below the base) with a warning, as the refill shortfall rule of 2026-11-18: the reserve is
    built as fast as possible, the plan stays feasible.
    """
    eff = float(bat["efficiency"])
    max_charge = float(bat.get("max_charge_power_kw", bat.get("max_power_kw") or 0.0) or 0.0)
    step = (max_charge * eff - idle_drain_kw(bat)) * dt_h
    out: list[float] = []
    short_slots = 0
    for k, floor in enumerate(plan.floor_kwh):
        if floor <= plan.base_kwh + _EPS:
            out.append(floor)
            continue
        reach = float(e_init) + (k + 1) * step
        if floor > reach + _EPS:
            short_slots += 1
            out.append(max(plan.base_kwh, reach))
        else:
            out.append(floor)
    if short_slots:
        logger.warning(
            "Virtuelle Reserve: Untergrenze %.3f kWh in %d Slot(s) vom Start (%.3f kWh) "
            "nicht erreichbar – auf das Erreichbare gesenkt, Aufbau so schnell wie möglich.",
            plan.reserve_floor_kwh,
            short_slots,
            float(e_init),
        )
    return out
