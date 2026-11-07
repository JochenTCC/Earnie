"""SE: how much heat of a heating rod the heat store can hold, per slot and across windows.

The rod only replaces heat of the main source. Its heat goes into the store and leaves it as the
source's heat of the year model (spread evenly over the day): while rod heat is left, the source
stays off. The store holds at most its band, volume × (setpoint − lower limit), and the level
starts empty, so the whole band counts as free. That is an upper bound: a real source also fills
the band, and a store held hotter loses more heat, which is not modeled.

The SE carries the level from window to window like the SoC. Live has its own bound from the
measured store (``thermal_flex_context.live_rod_heat_cap_kwh``) and never reads this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.thermal_coupled import normalize_heat_storage
from optimizer.thermal_model import capacity_kwh_per_k_from_volume

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext

# Key in the scenario settings of ``planning_scenario_scope``: rod id → level at the window's start.
ROD_STORE_START_KEY = "_rod_store_start_kwh"
STORE_BALANCE_CONTEXT_KEY = "store_balance"
_NO_HEAT_KWH = 1e-9


def next_level_kwh(level_kwh: float, heat_kwh: float, drain_kwh: float, capacity_kwh: float) -> float:
    """Level after one slot. The floor is the source taking over, the cap only absorbs solver noise."""
    return min(capacity_kwh, max(0.0, level_kwh + heat_kwh - drain_kwh))


@dataclass(frozen=True)
class RodStoreBalance:
    """``drain_kwh``: source heat per slot of the matrix; a slot without any keeps the rod off."""

    capacity_kwh: float
    start_kwh: float
    drain_kwh: list[float]

    def has_demand(self, slot: int) -> bool:
        return self.drain_kwh[slot] > _NO_HEAT_KWH


def rod_store_capacity_kwh(parent: dict) -> float:
    """Heat [kWh] the store holds between its lower limit and its setpoint."""
    thermal = parent.get("thermal") or parent
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    if storage is None:
        raise ValueError(
            f"Heizstab an '{parent.get('id')}': kein Wärmespeicher (heat_storage im Heizsystem)."
        )
    return capacity_kwh_per_k_from_volume(storage["volume_liters"]) * storage["tolerance_c"]


def rod_store_balance(
    matrix: list[dict],
    rod_id: str,
    parent: dict,
    house_profile: dict,
    *,
    start_levels_kwh: dict[str, float] | None,
    climate: ModeledClimateContext | None,
) -> RodStoreBalance:
    """Balance of one rod over ``matrix``. Without start levels the window stands alone: empty store."""
    from optimizer.thermal_flex_context import thermal_daily_heat_kwh_for_date

    capacity = rod_store_capacity_kwh(parent)
    heat_by_day: dict[date, float] = {}
    drain: list[float] = []
    for row in matrix:
        day = row["date"]
        if day not in heat_by_day:
            heat_by_day[day] = thermal_daily_heat_kwh_for_date(parent, house_profile, day, climate=climate)
        drain.append(heat_by_day[day] * float(DEFAULT_DT_H) / 24.0)
    start = float((start_levels_kwh or {}).get(rod_id, 0.0))
    return RodStoreBalance(capacity_kwh=capacity, start_kwh=min(start, capacity), drain_kwh=drain)
