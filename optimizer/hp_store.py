"""SE: how far a heat pump may shift its heat against the year model, per slot and across windows.

The MILP may move a heat pump's day energy inside its window. Without a limit any store, and no
store at all, allowed the same shift. Here the heat the pump (and a heating rod beside it) delivers
fills a level, the year model's heat of the slot empties it, and the level stays between 0 and the
capacity on every slot of the book (``optimizer.thermal_store_model``, shared with Live):

- with a store: the store's band, volume × (tolerance + boost) (``heat_storage``), with the
  store's leak (``heat_loss_kw_per_k``) toward the middle of the normal band. The house is a
  passive level (HeatControl P4, design § 8.6 D1): Earnie cannot charge it before P6, so its
  comfort band no longer adds capacity.
- without a store: the house's mass, ``house_capacity_kwh_per_k`` (living area × building mass) ×
  the comfort band ``house_tolerance_c``; the pump heats the house directly. No leak yet.

Without carried level the window starts at the reference level: a pump that follows the year
model stays there.

The SE carries the level from window to window like the SoC. Live builds its own store level
from the measured store (``thermal_live_store``) and never reads this module. The reference
rules of L2 do not use it either.
"""
from __future__ import annotations

from dataclasses import dataclass

from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.thermal_coupled import normalize_heat_storage
from optimizer.thermal_house import DEFAULT_HOUSE_TOLERANCE_C, house_capacity_kwh_per_k
from optimizer.thermal_model import capacity_kwh_per_k_from_volume
from optimizer.thermal_store_model import StoreLevelModel

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

    @property
    def level_kwh(self) -> float:
        """Capacity of the planned level: the store where there is one, else the house (D1)."""
        return self.store_kwh if self.store_kwh > 0.0 else self.house_kwh


@dataclass(frozen=True)
class HpStoreBalance:
    """``drain_kwh``: the year model's heat per slot of the matrix; ``efficiency``: JAZ of the pump.

    ``leak_per_slot`` / ``leak_ref_kwh``: the store's loss toward the middle of its normal band
    (0 without a store).
    """

    capacity_kwh: float
    start_kwh: float
    efficiency: float
    drain_kwh: list[float]
    leak_per_slot: float = 0.0
    leak_ref_kwh: float = 0.0

    def store_model(self, drain_kwh: list[float] | None = None) -> StoreLevelModel:
        return StoreLevelModel(
            capacity_kwh=self.capacity_kwh,
            start_kwh=self.start_kwh,
            efficiency=self.efficiency,
            drain_kwh=list(self.drain_kwh if drain_kwh is None else drain_kwh),
            leak_per_slot=self.leak_per_slot,
            leak_ref_kwh=self.leak_ref_kwh,
        )


def hp_store_capacity(source: dict) -> HpStoreCapacity:
    """Store band plus house mass of a heat pump's thermal block. Neither of them fails loud."""
    thermal = source.get("thermal") or source
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    store_kwh = (
        0.0
        if storage is None
        # Band below the setpoint plus the fixed boost above it (HeatControl P2).
        else capacity_kwh_per_k_from_volume(storage["volume_liters"])
        * (storage["tolerance_c"] + storage["boost_k"])
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


def _store_leak(source: dict) -> tuple[float, float]:
    """(leak per slot, reference level [kWh]) of the store; (0, None) without a store."""
    thermal = source.get("thermal") or source
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    if storage is None:
        return 0.0, None
    capacity_per_k = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    leak = DEFAULT_DT_H * float(storage["heat_loss_kw_per_k"]) / capacity_per_k
    # The year model's heat already holds the loss of normal operation, which stays between the
    # band minimum and the setpoint: the leak acts on the distance from the middle of that band.
    return leak, capacity_per_k * float(storage["tolerance_c"]) / 2.0


def hp_store_balance(
    hp_id: str,
    source: dict,
    slot_energy_kwh: list[float],
    efficiency: float,
    *,
    start_levels_kwh: dict[str, float] | None,
) -> HpStoreBalance:
    """Balance of one heat pump over the matrix; ``slot_energy_kwh`` is its year-model electricity."""
    capacity = hp_store_capacity(source).level_kwh
    leak, ref = _store_leak(source)
    reference = capacity / 2.0 if ref is None else min(ref, capacity)
    carried = (start_levels_kwh or {}).get(hp_id)
    start = reference if carried is None else min(max(0.0, float(carried)), capacity)
    return HpStoreBalance(
        capacity_kwh=capacity,
        start_kwh=start,
        efficiency=float(efficiency),
        drain_kwh=[float(kwh) * float(efficiency) for kwh in slot_energy_kwh],
        leak_per_slot=leak,
        leak_ref_kwh=reference,
    )


def next_hp_level_kwh(balance: HpStoreBalance, level_kwh: float, heat_kwh: float, slot: int) -> float:
    """Level after one booked slot; the clamp only absorbs solver noise and a booking off the plan."""
    leak = balance.leak_per_slot
    raw = (1.0 - leak) * level_kwh + leak * balance.leak_ref_kwh + heat_kwh - balance.drain_kwh[slot]
    return min(balance.capacity_kwh, max(0.0, raw))
