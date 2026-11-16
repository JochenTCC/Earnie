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
- Optional charge limit per slot below the capacity: the generator may not run on a slot whose
  level ends above it (room kept free for forecast collector heat). It uses the generator's
  existing on-variable, so it adds no binary. A limit at or above the capacity is none: the
  band's upper end holds as without it.

Sink segments (HeatControl P5, design § 8.2): with ``segments`` the band is split bottom-up
into parts with their own COP per slot, falling with the temperature. The generator's
electricity of a slot is split over the segments, ``Σ e_k = e_gen`` and
``heat = Σ cop_k · e_k``; the content ``s_k`` of a segment rises only by the heat put into
it and ``Σ s_k`` is the level. Filling takes the efficient segments first by cost. Draining
would keep the hot segments full and cycle the cheap ones, which the real store cannot do
(it cools from the top), so a segment may never be fuller than the one below it
(``s_k+1 / cap_k+1 ≤ s_k / cap_k``). That bounds the error without binaries: the plan can
hold at most the same fill fraction in a hot segment as in the one below while it recharges
the lower one at its COP.

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
class StoreSegment:
    """One part of the band, bottom-up: its heat [kWh] and the COP of charging it per slot."""

    capacity_kwh: float
    cop: list[float]


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
    # Sink segments, bottom-up; their capacities add up to ``capacity_kwh``. Empty: one
    # efficiency for the whole band (``efficiency``).
    segments: tuple[StoreSegment, ...] = ()
    # Level per matrix slot up to which the generator may charge (below the capacity); other
    # heat and the content already there may lie above it. Empty, or an entry at or above the
    # capacity = no limit on that slot.
    charge_limit_kwh: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.capacity_kwh < 0:
            raise ValueError(f"Speicherkapazität darf nicht negativ sein ({self.capacity_kwh:g} kWh).")
        if not 0.0 <= self.leak_per_slot < 1.0:
            raise ValueError(f"Speicherverlust je Slot muss in [0, 1) liegen ({self.leak_per_slot:g}).")
        if self.efficiency <= 0:
            raise ValueError(f"Wirkungsgrad muss > 0 sein ({self.efficiency:g}).")
        self._check_segments()

    def _check_segments(self) -> None:
        if not self.segments:
            return
        total = sum(segment.capacity_kwh for segment in self.segments)
        if any(segment.capacity_kwh <= 0 for segment in self.segments) or abs(
            total - self.capacity_kwh
        ) > 1e-6 * max(1.0, self.capacity_kwh):
            raise ValueError(
                f"Speichersegmente ({total:g} kWh) müssen positiv sein und zusammen die "
                f"Speicherkapazität ergeben ({self.capacity_kwh:g} kWh)."
            )
        slots = len(self.segments[0].cop)
        for index, segment in enumerate(self.segments):
            if len(segment.cop) != slots or any(cop <= 0 for cop in segment.cop):
                raise ValueError(
                    f"Speichersegment {index}: COP je Slot muss > 0 sein und für alle "
                    "Segmente gleich viele Slots haben."
                )
            if index and any(
                cop > below + 1e-9 for cop, below in zip(segment.cop, self.segments[index - 1].cop)
            ):
                raise ValueError(
                    f"Speichersegment {index}: der COP muss mit der Temperatur fallen "
                    "(er ist höher als im Segment darunter)."
                )


@dataclass
class StoreLevelVars:
    """Solver variables of one store level: level after each book slot, slack per slot."""

    levels: dict[int, Any]
    slack: dict[int, tuple[Any, Any]]
    terminal_slack: Any | None = None
    # With sink segments: generator electricity [kWh] per slot and segment (bottom-up).
    segment_charge: dict[int, list[Any]] = field(default_factory=dict)

    def segment_charge_kwh(self, slot: int) -> list[float]:
        return [_value(var) for var in self.segment_charge.get(slot, [])]

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


def _bounds(store: StoreLevelModel, step: int) -> tuple[float, float, float]:
    """Band [lower, upper] after ``step + 1`` slots and the part of ``upper`` above the capacity.

    A start outside the band decays with the leak.
    """
    decay = (1.0 - store.leak_per_slot) ** (step + 1)
    drifted = store.leak_ref_kwh + (store.start_kwh - store.leak_ref_kwh) * decay
    upper = max(store.capacity_kwh, drifted)
    return min(0.0, drifted), upper, upper - store.capacity_kwh


def _start_fill(store: StoreLevelModel) -> list[float]:
    """Content of the segments at the start: the level inside the band, filled bottom-up."""
    left = min(max(store.start_kwh, 0.0), store.capacity_kwh)
    fill: list[float] = []
    for segment in store.segments:
        fill.append(min(left, segment.capacity_kwh))
        left -= fill[-1]
    return fill


def _is_zero(expr: Any) -> bool:
    return isinstance(expr, (int, float)) and abs(expr) < 1e-12


def _split_generator(
    model: Any,
    name: str,
    store: StoreLevelModel,
    slot: int,
    generator_kwh: Any,
    segment_charge: dict[int, list[Any]],
) -> list[Any]:
    """Split the generator's electricity of ``slot`` over the segments; heat per segment."""
    if _is_zero(generator_kwh):
        return [0.0 for _segment in store.segments]
    parts = [
        pulp.LpVariable(f"{name}_seg{index}_e_{slot}", lowBound=0.0)
        for index in range(len(store.segments))
    ]
    model.prob += pulp.lpSum(parts) == generator_kwh, f"{name}_seg_split_{slot}"
    segment_charge[slot] = parts
    return [segment.cop[slot] * part for segment, part in zip(store.segments, parts)]


def _add_segment_fill(
    model: Any,
    name: str,
    store: StoreLevelModel,
    slot: int,
    fill: list[Any],
    charge_heat: list[Any],
    removal_kwh: float,
    free_heat: Any,
    uncounted_max: Any,
) -> list[Any]:
    """Content of the segments after ``slot``; returns it for the next slot.

    Each segment has its own balance in two steps, so that a slot which drains and charges
    cannot refill a segment at its COP while a hotter one stays full:

        mid_k  = (1 − a) · s_k − d_k          Σ d_k = removal − unmet
        s_k'   = mid_k + cop_k · e_k + f_k − u_k     Σ f_k = free heat

    with the fill order (``s_k+1 / cap_k+1 ≤ s_k / cap_k``) on ``mid`` and on ``s'``.
    ``removal`` is the heat drawn, ``free heat`` what is not the generator's (rods, collector
    heat, the leak toward a reference). ``unmet`` is draw from an empty store; it only leaves
    content standing, which never helps the plan. ``u`` is heat that does not fit (a level
    above the band); it is bounded by the band's slack and the drift of a start above the
    band, because uncounted heat would open room in the efficient segments. Only the top
    segment has it: by the fill order it is full only when all segments are.
    """
    segments = store.segments
    keep = 1.0 - store.leak_per_slot
    count = len(segments)

    def var(kind: str, index: int, **bounds: float) -> Any:
        return pulp.LpVariable(f"{name}_seg{index}_{kind}_{slot}", lowBound=0.0, **bounds)

    content = [var("s", index, upBound=segment.capacity_kwh) for index, segment in enumerate(segments)]
    # Variables only where there is something to distribute: fewer columns for the solver.
    drawn: list[Any] = [0.0] * count
    if removal_kwh > 1e-12:
        drawn = [var("d", index) for index in range(count)]
        unmet = pulp.LpVariable(f"{name}_seg_unmet_{slot}", lowBound=0.0)
        model.prob += pulp.lpSum(drawn) == removal_kwh - unmet, f"{name}_seg_draw_{slot}"
    free: list[Any] = [0.0] * count
    if not _is_zero(free_heat):
        free = [var("f", index) for index in range(count)]
        model.prob += pulp.lpSum(free) == free_heat, f"{name}_seg_free_{slot}"
    # Heat that does not fit: by the fill order the top segment is full only when all are.
    uncounted: list[Any] = [0.0] * count
    uncounted[-1] = var("u", count - 1)
    model.prob += uncounted[-1] <= uncounted_max, f"{name}_seg_uncounted_{slot}"
    mid = [keep * fill[index] - drawn[index] for index in range(count)]
    for index, segment in enumerate(segments):
        if removal_kwh > 1e-12:
            model.prob += mid[index] >= 0, f"{name}_seg{index}_mid_{slot}"
        model.prob += (
            content[index] == mid[index] + charge_heat[index] + free[index] - uncounted[index],
            f"{name}_seg{index}_balance_{slot}",
        )
        if index:
            lower = segments[index - 1].capacity_kwh
            if removal_kwh > 1e-12:  # without a draw the order of the slot before still holds
                model.prob += (
                    mid[index] * lower <= mid[index - 1] * segment.capacity_kwh,
                    f"{name}_seg{index}_order_mid_{slot}",
                )
            model.prob += (
                content[index] * lower <= content[index - 1] * segment.capacity_kwh,
                f"{name}_seg{index}_order_{slot}",
            )
    return content


def add_store_level(
    model: Any,
    name: str,
    store: StoreLevelModel,
    book: list[int],
    heat_kwh_at: Callable[[int], Any],
    *,
    generator_kwh_at: Callable[[int], Any] | None = None,
    generator_on_at: Callable[[int], Any] | None = None,
) -> StoreLevelVars:
    """Add the level of ``store`` over the slots ``book`` (ascending, contiguous) to ``model``.

    ``heat_kwh_at(slot)`` is the heat [kWh] put into the store on ``slot`` as an expression of
    the solver variables (generator × efficiency plus rods); 0 where nothing may run.

    With ``store.segments`` the generator comes separately: ``generator_kwh_at(slot)`` is its
    electricity [kWh] (0 where it may not run) and ``heat_kwh_at`` only the other heat (rods).

    With ``store.charge_limit_kwh``, ``generator_on_at(slot)`` is the generator's on-variable
    (0/1) of the slot.
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
    if store.segments and generator_kwh_at is None:
        raise ValueError(f"Speicher {name}: Segmente brauchen den Strom des Erzeugers je Slot.")
    if generator_kwh_at is not None and not store.segments:
        raise ValueError(f"Speicher {name}: Strom des Erzeugers ohne Segmente übergeben.")
    if store.segments and book[-1] >= len(store.segments[0].cop):
        raise ValueError(
            f"Speicher {name}: COP der Segmente reicht nicht bis Slot {book[-1]} "
            f"(nur {len(store.segments[0].cop)} Slots)."
        )
    if store.charge_limit_kwh and generator_on_at is None:
        raise ValueError(f"Speicher {name}: Ladegrenze braucht die Ein-Variable des Erzeugers.")
    fill: list[Any] = _start_fill(store)
    segment_charge: dict[int, list[Any]] = {}
    leak = store.leak_per_slot
    level: Any = store.start_kwh
    levels: dict[int, Any] = {}
    slack: dict[int, tuple[Any, Any]] = {}
    penalty = pulp.LpAffineExpression()
    for step, slot in enumerate(book):
        lower, upper, over = _bounds(store, step)
        spill_max = store.spill_max_kwh[slot] if slot < len(store.spill_max_kwh) else 0.0
        other_heat = heat_kwh_at(slot)
        inflow = other_heat - store.drain_kwh[slot]
        charge_heat: list[Any] = []
        if store.segments:
            charge_heat = _split_generator(
                model, name, store, slot, generator_kwh_at(slot), segment_charge
            )
            inflow = inflow + pulp.lpSum(charge_heat)
        spill: Any = 0.0
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
        if (
            slot < len(store.charge_limit_kwh)
            and store.charge_limit_kwh[slot] < store.capacity_kwh - 1e-9
        ):
            limit = float(store.charge_limit_kwh[slot])
            # Generator on → the level ends at or below the limit; off → the band's upper end.
            model.prob += (
                next_level <= upper - (upper - limit) * generator_on_at(slot) + above,
                f"{name}_charge_limit_{slot}",
            )
        penalty += STORE_SLACK_PENALTY_CENT_PER_KWH * (below + above)
        levels[slot] = next_level
        slack[slot] = (below, above)
        level = next_level
        if store.segments:
            # Heat that is not the generator's: rods, collector heat (a negative drain, less
            # what is spilled) and the leak toward the reference.
            drain = float(store.drain_kwh[slot])
            leak_in = leak * float(store.leak_ref_kwh)
            free_heat = other_heat + max(0.0, -drain) + max(0.0, leak_in) - spill
            removal = max(0.0, drain) + max(0.0, -leak_in)
            fill = _add_segment_fill(
                model, name, store, slot, fill, charge_heat, removal, free_heat, above + over
            )
    terminal_slack = None
    if store.terminal_min_kwh is not None:
        terminal_slack = pulp.LpVariable(f"{name}_terminal_below", lowBound=0.0)
        model.prob += (
            level >= float(store.terminal_min_kwh) - terminal_slack,
            f"{name}_terminal",
        )
        penalty += STORE_SLACK_PENALTY_CENT_PER_KWH * terminal_slack
    model.prob.objective += penalty
    return StoreLevelVars(
        levels=levels, slack=slack, terminal_slack=terminal_slack, segment_charge=segment_charge
    )
