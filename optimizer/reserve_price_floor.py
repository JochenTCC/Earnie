"""Price-aware floor of the virtual powerstation reserve, per slot (Reserve P2).

The reserve is held in slot ``t`` only where feeding from the battery is cheaper than the grid:

    price[t] > fill_cost(t)

``fill_cost(t)`` is the cheapest way to have the reserve in the battery at ``t``:

- from a slot ``s < t`` of the horizon: ``price[s] / eta_rt + hold(s, t)``,
- from energy already stored (the persisted fill basis, see
  ``runtime_store.powerstation_reserves``): ``basis / eta_rt + hold(slot 0, t)``. The fill
  price is paid and the hold time up to now is sunk; only the hold from now on counts.

``eta_rt`` is the round trip of the battery, ``efficiency ** 2`` (the MILP applies
``efficiency`` once on charge and once on discharge). ``hold`` is the idle drain over the hold
time (``idle_drain_hold_kwh``), bought at the fill price through the charge path and spread
over the reserve's kWh. Slot 0 has no slot before it: it only pays through the fill basis.

The floor binds the stored energy at the start and the end of a paying slot. ``e_batt[k]`` is
the energy at the end of slot ``k`` (start of ``k + 1``), so it carries the reserve when slot
``k`` or slot ``k + 1`` pays. The cost objective then builds the reserve in the cheapest slots
before the first paying slot, like an EV charging deadline.

Tolerance at the floor (Reserve P3, ``banded_floor_kwh``): the plant reads the SoC in whole
percent. In the paying slots from slot 0 on, a start energy inside the band below the floor or
within one reading step above it is held where it is: the bound follows the idle drain, so the
plan neither releases a discharge nor refills a gap at once. A start below the band is refilled
in one block up to the floor.
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

# The plant reports the SoC in whole percent; a floor such as 12.33 % reads as 12 % or 13 %
# although the true SoC sits on the floor.
SOC_READING_RESOLUTION_PCT = 1.0
# Refill band (Reserve P3): at least this many reading steps, so that one reading step of drain
# never triggers a refill.
BAND_MIN_READING_STEPS = 2
# Refill band (Reserve P3): at least the idle drain over this many slots, so that one refill
# block lasts that long before the next one.
BAND_HOLD_SLOTS = 8

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
            "Füllzeitpunkt der Reserve nicht bestimmbar."
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
    if basis_price is not None and horizon > 0:
        basis_at = _parse_basis_at(bat[BASIS_AT_KEY])

    pays: list[bool] = []
    fill_price: list[float | None] = []
    fill_at: list[datetime | None] = []
    for t in range(horizon):
        best_cost: float | None = None
        best_price: float | None = None
        # Fill source: index of the horizon slot, or None for the persisted basis.
        best_slot: int | None = None
        if basis_price is not None:
            # Energy already stored: fill price and past hold time are sunk, the hold
            # from the start of slot 0 on is what keeping it costs from now.
            best_cost = cost(float(basis_price), t * dt_h)
            best_price = float(basis_price)
        for s in range(t):
            c = cost(prices[s], (t - s) * dt_h)
            if best_cost is None or c < best_cost - _EPS:
                best_cost, best_price, best_slot = c, prices[s], s
        ok = best_cost is not None and prices[t] > best_cost + _EPS
        pays.append(ok)
        fill_price.append(best_price if ok else None)
        if not ok:
            fill_at.append(None)
        elif best_slot is None:
            fill_at.append(basis_at)
        else:
            # The fill time becomes the persisted basis (update_reserve_fill_basis):
            # validated here, before the model is built, not after the plan.
            fill_at.append(slot_start(matrix, best_slot))

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


def reserve_floor_band_soc_pct(bat: dict, *, dt_h: float) -> float:
    """Width of the refill band below the reserve floor in SoC points (Reserve P3).

    ``max(BAND_MIN_READING_STEPS · SOC_READING_RESOLUTION_PCT, drain over BAND_HOLD_SLOTS)``:
    the idle drain (``idle_drain_hold_kwh``) of ``BAND_HOLD_SLOTS`` slots, so that one refill
    block lasts that many slots, but never less than two reading steps. Without a configured
    drain the band is the minimum.
    """
    if dt_h <= 0.0:
        raise ValueError(f"reserve_floor_band_soc_pct: dt_h must be > 0, got {dt_h}")
    capacity = float(bat["battery_capacity_kwh"])
    if capacity <= 0.0:
        raise ValueError(f"Virtuelle Reserve: battery_capacity_kwh {capacity!r} <= 0.")
    minimum = BAND_MIN_READING_STEPS * SOC_READING_RESOLUTION_PCT
    drain_pct = idle_drain_hold_kwh(bat, BAND_HOLD_SLOTS * dt_h) / capacity * 100.0
    return max(minimum, drain_pct)


def banded_floor_kwh(
    plan: ReserveFloorPlan,
    bat: dict,
    *,
    e_init: float,
    dt_h: float,
) -> list[float]:
    """``plan.floor_kwh`` with the tolerance at the floor applied (Reserve P3).

    Only the paying run that starts at slot 0 (``floor_kwh[k]`` above the base from ``k = 0``
    on) changes; later paying runs keep the full floor, which the plan builds up in the slots
    before them as in P2. With ``F`` the reserve floor, ``s`` one reading step, ``B`` the band
    (``reserve_floor_band_soc_pct``) and ``d`` the idle drain of one slot:

    - ``e_init > F + s``: unchanged. The energy above the floor is free energy.
    - ``F − B ≤ e_init ≤ F + s`` (inside the band): hold. The bound at the end of slot ``k`` is
      ``e_init − d · (k + 1)``, the energy the drain alone leaves. The plan neither discharges
      (no Automatik release one step above the floor) nor has to charge (no refill of a gap
      inside the band).
    - ``e_init < F − B`` (gap beyond the band): one block up to the floor. The bound is ``F`` at
      the end of slot 0 and ``F − d · k`` after it, so the block is exactly the gap plus the
      drain of slot 0, and nothing is topped up afterwards. ``reachable_floor_kwh`` spreads a
      block the battery cannot charge in one slot over the next slots.

    All bounds stay at or above the base ``min_soc``. In the run the bound follows the drain
    and is not held at ``F − B``: the band is enforced by the next cycles, which see the
    reading leave the band and refill. A bound held at ``F − B`` would make the plan top up the
    drain in small charges, and with equal prices in slot 0.
    """
    floors = list(plan.floor_kwh)
    if not plan.held_now:
        return floors
    capacity = float(bat["battery_capacity_kwh"])
    step_kwh = SOC_READING_RESOLUTION_PCT / 100.0 * capacity
    band_kwh = reserve_floor_band_soc_pct(bat, dt_h=dt_h) / 100.0 * capacity
    floor = plan.reserve_floor_kwh
    bottom = max(plan.base_kwh, floor - band_kwh)
    start = float(e_init)
    if start > floor + step_kwh + _EPS:
        return floors
    drain_kwh = idle_drain_kw(bat) * dt_h
    refill = start < bottom - _EPS
    for k, value in enumerate(floors):
        if value <= plan.base_kwh + _EPS:
            break
        held = floor - drain_kwh * k if refill else start - drain_kwh * (k + 1)
        floors[k] = max(plan.base_kwh, held)
    if refill:
        logger.info(
            "Virtuelle Reserve: Start %.3f kWh unter dem Band (%.3f kWh) – ein Nachladeblock "
            "bis zur Untergrenze %.3f kWh.",
            start,
            bottom,
            floor,
        )
    else:
        logger.info(
            "Virtuelle Reserve: Start %.3f kWh im Toleranzband [%.3f, %.3f] kWh um die "
            "Untergrenze %.3f kWh – halten, weder nachladen noch entladen.",
            start,
            bottom,
            floor + step_kwh,
            floor,
        )
    return floors


def reachable_floor_kwh(
    floors: list[float],
    plan: ReserveFloorPlan,
    bat: dict,
    *,
    e_init: float,
    dt_h: float,
) -> list[float]:
    """``floors`` (the plan's floor per slot) lowered where the battery cannot reach it from ``e_init``.

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
    for k, floor in enumerate(floors):
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


def effective_floor_kwh(
    bat: dict,
    matrix: list[dict[str, Any]],
    *,
    horizon: int,
    e_init: float,
    dt_h: float,
) -> tuple[ReserveFloorPlan, list[float]] | None:
    """Price-aware floor per slot with tolerance and reachability; ``None`` without a reserve.

    The one place the MILP bound and the Automatik discharge cap take the floor from.
    """
    plan = reserve_price_floor(bat, matrix, horizon=horizon, dt_h=dt_h)
    if plan is None:
        return None
    banded = banded_floor_kwh(plan, bat, e_init=e_init, dt_h=dt_h)
    return plan, reachable_floor_kwh(banded, plan, bat, e_init=e_init, dt_h=dt_h)
