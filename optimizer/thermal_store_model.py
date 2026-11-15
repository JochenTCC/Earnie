"""One linear store level inside the MILP, shared by Live and the SE (HeatControl P4).

Design: docs/dev/heat-control-sg-ready.md § 8.1, § 8.4 (O1: inside the MILP) and § 8.6.

Per slot ``t`` of the book the level ``x`` [kWh] follows

    x[t+1] = (1 − a) · x[t] + a · ref + efficiency · e_gen[t] + e_rod[t] − drain[t] − spill[t]

- ``a`` = Δt · H / C: the store's leak toward ``ref``; ``drain`` already holds the loss at
  ``ref`` (Live: the loss at the band minimum, ``ref`` = 0). ``a`` = 0 is the loss-free level.
- ``spill`` ≤ ``spill_max``: heat that may stay out of the store (collector heat on a full
  store); it costs nothing.
- ``0 ≤ x ≤ capacity`` with slack at ``STORE_SLACK_PENALTY_CENT_PER_KWH``. A start outside the
  band moves the bound with the leak, so the start itself costs no slack.
- Optional terminal level: ``x[end] ≥ terminal_min`` (slack at the same price).

No binaries; the level may never gain anything by sitting off the real value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pulp

STORE_SLACK_PENALTY_CENT_PER_KWH = 200.0
"""Heat [kWh] outside the store's band costs this much, so a band that cannot hold (a short
window, pulse limits, too little power) never makes the plan infeasible. Same value as the
import cap's slack; far above any price, so the plan only leaves the band when nothing else
works."""

STORE_SLACK_REPORT_KWH = 0.05
"""Slack below this is solver noise and not reported."""


@dataclass(frozen=True)
class StoreLevelModel:
    """Parameters of one store level over the matrix (lists indexed by matrix slot)."""

    capacity_kwh: float
    start_kwh: float
    efficiency: float
    drain_kwh: list[float]
    leak_per_slot: float = 0.0
    leak_ref_kwh: float = 0.0
    spill_max_kwh: list[float] = field(default_factory=list)
    terminal_min_kwh: float | None = None

    def __post_init__(self) -> None:
        if self.capacity_kwh < 0:
            raise ValueError(f"Speicherkapazität darf nicht negativ sein ({self.capacity_kwh:g} kWh).")
        if not 0.0 <= self.leak_per_slot < 1.0:
            raise ValueError(f"Speicherverlust je Slot muss in [0, 1) liegen ({self.leak_per_slot:g}).")
        if self.efficiency <= 0:
            raise ValueError(f"Wirkungsgrad muss > 0 sein ({self.efficiency:g}).")


@dataclass
class StoreLevelVars:
    """Solver variables of one store level: level after each book slot, slack per slot."""

    levels: dict[int, Any]
    slack: dict[int, tuple[Any, Any]]
    terminal_slack: Any | None = None

    def level_kwh(self, slot: int) -> float:
        return _value(self.levels[slot])

    def slack_kwh(self) -> float:
        """Largest distance [kWh] of the level from its band (a slot or the terminal level)."""
        worst = max(
            (_value(below) + _value(above) for below, above in self.slack.values()), default=0.0
        )
        if self.terminal_slack is not None:
            worst = max(worst, _value(self.terminal_slack))
        return worst


def _value(var: Any) -> float:
    return float(getattr(var, "varValue", None) or 0.0)


def _bounds(store: StoreLevelModel, step: int) -> tuple[float, float]:
    """Band [lower, upper] after ``step + 1`` slots; a start outside it decays with the leak."""
    decay = (1.0 - store.leak_per_slot) ** (step + 1)
    drifted = store.leak_ref_kwh + (store.start_kwh - store.leak_ref_kwh) * decay
    return min(0.0, drifted), max(store.capacity_kwh, drifted)


def add_store_level(
    model: Any,
    name: str,
    store: StoreLevelModel,
    book: list[int],
    heat_kwh_at: Callable[[int], Any],
) -> StoreLevelVars:
    """Add the level of ``store`` over the slots ``book`` (ascending, contiguous) to ``model``.

    ``heat_kwh_at(slot)`` is the heat [kWh] put into the store on ``slot`` as an expression of
    the solver variables (generator × efficiency plus rods); 0 where nothing may run.
    """
    if not book:
        return StoreLevelVars(levels={}, slack={})
    if book != list(range(book[0], book[-1] + 1)):
        raise ValueError(f"Speicher {name}: Buchungsslots müssen lückenlos aufsteigen.")
    if book[-1] >= len(store.drain_kwh):
        raise ValueError(
            f"Speicher {name}: Wärmeentnahme reicht nicht bis Slot {book[-1]} "
            f"(nur {len(store.drain_kwh)} Slots)."
        )
    leak = store.leak_per_slot
    level: Any = store.start_kwh
    levels: dict[int, Any] = {}
    slack: dict[int, tuple[Any, Any]] = {}
    penalty = pulp.LpAffineExpression()
    for step, slot in enumerate(book):
        lower, upper = _bounds(store, step)
        spill_max = store.spill_max_kwh[slot] if slot < len(store.spill_max_kwh) else 0.0
        inflow = heat_kwh_at(slot) - store.drain_kwh[slot]
        if spill_max > 1e-12:
            spill = pulp.LpVariable(f"{name}_spill_{slot}", lowBound=0.0, upBound=spill_max)
            inflow = inflow - spill
        next_level = pulp.LpVariable(f"{name}_level_{slot}")
        model.prob += (
            next_level == (1.0 - leak) * level + leak * store.leak_ref_kwh + inflow,
            f"{name}_balance_{slot}",
        )
        below = pulp.LpVariable(f"{name}_below_{slot}", lowBound=0.0)
        above = pulp.LpVariable(f"{name}_above_{slot}", lowBound=0.0)
        model.prob += next_level >= lower - below, f"{name}_floor_{slot}"
        model.prob += next_level <= upper + above, f"{name}_cap_{slot}"
        penalty += STORE_SLACK_PENALTY_CENT_PER_KWH * (below + above)
        levels[slot] = next_level
        slack[slot] = (below, above)
        level = next_level
    terminal_slack = None
    if store.terminal_min_kwh is not None:
        terminal_slack = pulp.LpVariable(f"{name}_terminal_below", lowBound=0.0)
        model.prob += (
            level >= float(store.terminal_min_kwh) - terminal_slack,
            f"{name}_terminal",
        )
        penalty += STORE_SLACK_PENALTY_CENT_PER_KWH * terminal_slack
    model.prob.objective += penalty
    return StoreLevelVars(levels=levels, slack=slack, terminal_slack=terminal_slack)
