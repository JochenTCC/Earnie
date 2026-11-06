"""Chart 2 as an account view: balances, gap and consumption control. Pure, no Streamlit.

Spec ``docs/dev/chart2-account-view.md`` §§ 3–5. A balance is the negative cumulative
cost: a falling line means paying. Both lines start at 0 € at the window start; the
mode "Ist bei Jetzt" shifts the baseline by the saving so far, so both lines meet at
*Jetzt*. The gap is signed like the ledger: positive = saved.

Slots left of *Jetzt* come from the savings ledger (optimized = ``cost_with``,
baseline = ``cost_without``); slots right of it from the plan. Skipped slots and
slots without ledger data count as zero on both sides.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

ANCHOR_NOW = "jetzt"
ANCHOR_START = "start"
ANCHOR_MODES = (ANCHOR_NOW, ANCHOR_START)

SLOT_COUNTED = "counted"
SLOT_SKIPPED = "skipped"
SLOT_NO_DATA = "no_data"
SLOT_PENDING = "pending"
SLOT_PLAN = "plan"
SLOT_STATES = (SLOT_COUNTED, SLOT_SKIPPED, SLOT_NO_DATA, SLOT_PENDING, SLOT_PLAN)
# Shown orange: the ledger did not count these slots, so they add nothing to either line.
SLOT_STATES_MARKED = frozenset({SLOT_SKIPPED, SLOT_NO_DATA})

# Spec § 6 item 5 (decided 2026-11-05): flag the plan's energy difference from these.
ENERGY_DIFF_MIN_KWH = 0.5
ENERGY_DIFF_MIN_SHARE = 0.02


@dataclass(frozen=True)
class AccountSlots:
    """Per-slot input of one chart window, all lists of the same length.

    ``anchor`` is the slot boundary of *Jetzt*, clamped to the window: 0 for a window
    that lies in the future, ``len`` for one that lies fully in the past. The two
    ``*_after_window_kwh`` values are the plan energy between the window end and the
    horizon end, so the consumption control reaches zero at the horizon end.
    """

    with_eur: tuple[float, ...]
    without_eur: tuple[float, ...]
    baseline_kwh: tuple[float, ...]
    optimized_kwh: tuple[float, ...]
    states: tuple[str, ...]
    anchor: int
    baseline_after_window_kwh: float = 0.0
    optimized_after_window_kwh: float = 0.0

    def __post_init__(self) -> None:
        count = len(self.states)
        for name in ("with_eur", "without_eur", "baseline_kwh", "optimized_kwh"):
            values = getattr(self, name)
            if len(values) != count:
                raise ValueError(f"account view: {name} has {len(values)} slots, states {count}")
            for index, value in enumerate(values):
                if not math.isfinite(value):
                    raise ValueError(f"account view: {name}[{index}] is not a number ({value})")
        unknown = set(self.states) - set(SLOT_STATES)
        if unknown:
            raise ValueError(f"account view: unknown slot states {sorted(unknown)}")
        if not 0 <= self.anchor <= count:
            raise ValueError(f"account view: anchor {self.anchor} outside 0..{count}")
        for name in ("baseline_after_window_kwh", "optimized_after_window_kwh"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"account view: {name} is not a number")


@dataclass(frozen=True)
class AccountView:
    """Balances at the slot boundaries (``len + 1`` points) and the figures of the labels."""

    mode: str
    anchor: int
    optimized: tuple[float, ...]
    baseline: tuple[float, ...]
    gap: tuple[float, ...]
    consumption_gap_kwh: tuple[float, ...]
    saving_so_far_eur: float
    saving_after_eur: float
    plan_energy_diff_kwh: float
    plan_energy_kwh: float

    @property
    def slot_count(self) -> int:
        return len(self.optimized) - 1

    @property
    def has_past(self) -> bool:
        return self.anchor > 0

    @property
    def has_future(self) -> bool:
        return self.anchor < self.slot_count

    @property
    def saving_total_eur(self) -> float:
        return self.saving_so_far_eur + self.saving_after_eur

    @property
    def flag_energy_difference(self) -> bool:
        """The plan compares unequal energies: "erwartet" also holds the price of the difference."""
        diff = abs(self.plan_energy_diff_kwh)
        return (
            self.has_future
            and diff >= ENERGY_DIFF_MIN_KWH
            and diff >= ENERGY_DIFF_MIN_SHARE * abs(self.plan_energy_kwh)
        )


def _balances(costs: Sequence[float]) -> list[float]:
    points = [0.0]
    for cost in costs:
        points.append(points[-1] - float(cost))
    return points


def build_account_view(slots: AccountSlots, mode: str) -> AccountView:
    if mode not in ANCHOR_MODES:
        raise ValueError(f"account view: unknown anchor mode {mode!r}")
    anchor = slots.anchor
    optimized = _balances(slots.with_eur)
    raw_baseline = _balances(slots.without_eur)
    savings = [b - a for a, b in zip(slots.with_eur, slots.without_eur)]
    so_far = sum(savings[:anchor])
    after = sum(savings[anchor:])
    shift = so_far if mode == ANCHOR_NOW else 0.0
    baseline = [value + shift for value in raw_baseline]
    if mode == ANCHOR_NOW:
        # Left of Jetzt: saved from here to Jetzt; right of it: saved from Jetzt to here.
        gap = [
            (baseline[k] - optimized[k]) if k < anchor else (optimized[k] - baseline[k])
            for k in range(len(optimized))
        ]
    else:
        gap = [optimized[k] - baseline[k] for k in range(len(optimized))]
    remaining = slots.baseline_after_window_kwh - slots.optimized_after_window_kwh
    consumption = [remaining]
    for base_kwh, opt_kwh in zip(reversed(slots.baseline_kwh), reversed(slots.optimized_kwh)):
        consumption.append(consumption[-1] + float(base_kwh) - float(opt_kwh))
    consumption.reverse()
    plan_energy = sum(slots.optimized_kwh[anchor:]) + slots.optimized_after_window_kwh
    return AccountView(
        mode=mode,
        anchor=anchor,
        optimized=tuple(optimized),
        baseline=tuple(baseline),
        gap=tuple(gap),
        consumption_gap_kwh=tuple(consumption),
        saving_so_far_eur=so_far,
        saving_after_eur=after,
        plan_energy_diff_kwh=consumption[anchor],
        plan_energy_kwh=plan_energy,
    )


@dataclass(frozen=True)
class GapRun:
    """One stretch between the two lines with one sign; positions are fractional boundaries."""

    saving: bool
    positions: tuple[float, ...]
    optimized: tuple[float, ...]
    baseline: tuple[float, ...]


def gap_runs(view: AccountView) -> list[GapRun]:
    """Split the area between the lines where the lines cross, coloured by the gap's sign.

    Within a slot both lines are linear, so a crossing is interpolated. The anchor in
    "Ist bei Jetzt" is a meeting point of the lines, never inside a run.
    """
    runs: list[GapRun] = []
    current: list[tuple[float, float, float]] = []
    sign: bool | None = None

    def close() -> None:
        nonlocal current, sign
        if sign is not None and len(current) >= 2:
            runs.append(
                GapRun(
                    saving=sign,
                    positions=tuple(p for p, _, _ in current),
                    optimized=tuple(o for _, o, _ in current),
                    baseline=tuple(b for _, _, b in current),
                )
            )
        current = []
        sign = None

    def point_sign(k: int) -> bool | None:
        value = view.gap[k]
        if abs(value) < 1e-9:
            return None
        return value > 0

    for k in range(len(view.optimized)):
        here = point_sign(k)
        point = (float(k), view.optimized[k], view.baseline[k])
        if here is None:
            if sign is not None:
                current.append(point)
                close()
            current = [point]
            continue
        if sign is None:
            sign = here
            current.append(point)
            continue
        if here == sign:
            current.append(point)
            continue
        # Sign change inside the slot k-1 → k: the lines cross there.
        previous_diff = view.optimized[k - 1] - view.baseline[k - 1]
        diff = view.optimized[k] - view.baseline[k]
        fraction = previous_diff / (previous_diff - diff) if previous_diff != diff else 0.5
        cross_value = view.optimized[k - 1] + fraction * (view.optimized[k] - view.optimized[k - 1])
        crossing = (k - 1 + fraction, cross_value, cross_value)
        current.append(crossing)
        close()
        sign = here
        current = [crossing, point]
    close()
    return runs
