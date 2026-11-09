"""SE: how far a heat pump may shift its heat against the year model, per slot and across windows.

The MILP may move a heat pump's day energy inside its window. Without a limit any store, and no
store at all, allowed the same shift. Here the heat the pump (and a heating rod beside it) delivers
fills a level, the year model's heat of the slot empties it, and the level stays between 0 and the
capacity on every slot of the book:

- the store's band, volume × tolerance (``heat_storage``), and
- the house's mass, ``house_capacity_kwh_per_k`` (living area × building mass) × the comfort band
  ``house_tolerance_c``.

A house with a store gets both, so a store never allows less shift than none. Without carried level
the window starts in the middle of the band: a pump that follows the year model stays there.

The SE carries the level from window to window like the SoC. Live plans the house and the store
itself (``thermal_live_house``, ``thermal_live_store``) and never reads this module. The reference
rules of L2 do not use it either.
"""
from __future__ import annotations

from dataclasses import dataclass

from optimizer.thermal_coupled import normalize_heat_storage
from optimizer.thermal_house import DEFAULT_HOUSE_TOLERANCE_C, house_capacity_kwh_per_k
from optimizer.thermal_model import capacity_kwh_per_k_from_volume

# Key in the scenario settings of ``planning_scenario_scope``: heat pump id → level at the window's start.
HP_STORE_START_KEY = "_hp_store_start_kwh"
HP_STORE_CONTEXT_KEY = "hp_store_balance"


@dataclass(frozen=True)
class HpStoreCapacity:
    """Heat [kWh] the store's band and the house's comfort band hold."""

    store_kwh: float
    house_kwh: float

    @property
    def total_kwh(self) -> float:
        return self.store_kwh + self.house_kwh


@dataclass(frozen=True)
class HpStoreBalance:
    """``drain_kwh``: the year model's heat per slot of the matrix; ``efficiency``: JAZ of the pump."""

    capacity_kwh: float
    start_kwh: float
    efficiency: float
    drain_kwh: list[float]


def hp_store_capacity(source: dict) -> HpStoreCapacity:
    """Store band plus house mass of a heat pump's thermal block. Neither of them fails loud."""
    thermal = source.get("thermal") or source
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    store_kwh = (
        0.0
        if storage is None
        else capacity_kwh_per_k_from_volume(storage["volume_liters"]) * storage["tolerance_c"]
    )
    living = float(thermal.get("living_area_m2", 0.0) or 0.0)
    tol_raw = thermal.get("house_tolerance_c")
    tolerance = DEFAULT_HOUSE_TOLERANCE_C if tol_raw in (None, "") else max(0.0, float(tol_raw))
    house_kwh = house_capacity_kwh_per_k(living, thermal.get("building_mass")) * tolerance
    if store_kwh + house_kwh <= 0.0:
        raise ValueError(
            f"Wärmepumpe '{source.get('id')}': keine Speichergrenze für den Szenarien-Explorer "
            "(weder Wärmespeicher noch Wohnfläche mit Komfortband)."
        )
    return HpStoreCapacity(store_kwh=store_kwh, house_kwh=house_kwh)


def hp_store_balance(
    hp_id: str,
    source: dict,
    slot_energy_kwh: list[float],
    efficiency: float,
    *,
    start_levels_kwh: dict[str, float] | None,
) -> HpStoreBalance:
    """Balance of one heat pump over the matrix; ``slot_energy_kwh`` is its year-model electricity."""
    capacity = hp_store_capacity(source).total_kwh
    carried = (start_levels_kwh or {}).get(hp_id)
    start = capacity / 2.0 if carried is None else min(max(0.0, float(carried)), capacity)
    return HpStoreBalance(
        capacity_kwh=capacity,
        start_kwh=start,
        efficiency=float(efficiency),
        drain_kwh=[float(kwh) * float(efficiency) for kwh in slot_energy_kwh],
    )


def next_hp_level_kwh(level_kwh: float, heat_kwh: float, drain_kwh: float, capacity_kwh: float) -> float:
    """Level after one booked slot; the clamp only absorbs solver noise and a booking off the plan."""
    return min(capacity_kwh, max(0.0, level_kwh + heat_kwh - drain_kwh))
