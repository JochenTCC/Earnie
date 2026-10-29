"""Fixed load inside the SE energy balance: native filter runs and continuous generics.

Both are booked in ``expected_p_act`` (``Verbrauch-Prognose``) instead of being
planned by the MILP, and counted on the consumer's column resp. as flex in the
plausibility check:

- the native pool-filter duty cycle (``filter_schedule.config_fallback``), see
  ``optimizer.filter_context``;
- continuous loads (``continuous_load`` on the MILP consumer, set by
  ``house_config.planning_flex_converters`` for a generic run >= 24 h on every
  weekday): such a run never ends inside a book window, so the generic target
  rule would drop it while the reference model keeps it as constant load.

Live does not build its matrix through this module (a continuous load attached
to a standby powerstation is served by ``optimizer.powerstation_standby``).
"""
from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from optimizer.filter_context import logged_native_filter_windows, native_filter_kw_at
from optimizer.slot_duration import DEFAULT_DT_H


def is_continuous_load(consumer: dict) -> bool:
    """MILP consumer flagged as continuous load with a positive nominal power."""
    return bool(consumer.get("continuous_load")) and float(
        consumer.get("nominal_power_kw", 0.0) or 0.0
    ) > 0.0


def continuous_load_kw(consumers: list | None) -> dict[str, float]:
    """``{consumer_id: nominal_kw}`` of every continuous load among ``consumers``."""
    return {
        str(consumer["id"]): float(consumer["nominal_power_kw"])
        for consumer in consumers or []
        if is_continuous_load(consumer)
    }


class FixedLoadWindows(NamedTuple):
    """Resolved fixed loads of one consumer list."""

    native_filter: dict[str, tuple[float, float, float]]
    continuous: dict[str, float]

    def __bool__(self) -> bool:
        return bool(self.native_filter or self.continuous)


def resolve_fixed_load_windows(consumers: list | None) -> FixedLoadWindows:
    return FixedLoadWindows(
        native_filter=logged_native_filter_windows(consumers or []),
        continuous=continuous_load_kw(consumers),
    )


def fixed_load_kw_at(windows: FixedLoadWindows, slot_dt: datetime) -> dict[str, float]:
    """Fixed kW per consumer in ``slot_dt`` (empty when nothing is booked)."""
    out = native_filter_kw_at(windows.native_filter, slot_dt)
    out.update(windows.continuous)
    return out


def adjust_targets_for_continuous_load(
    targets: dict[str, float],
    consumers: list | None,
    credit_slots: int,
) -> dict[str, float]:
    """Credit the fixed continuous energy of ``credit_slots`` against the target.

    The SE target of a continuous load is nominal × hours of the book window and
    the same energy sits in ``expected_p_act``; the MILP must not plan it again.
    Live targets of such consumers are 0 (manual), so this is a no-op there.
    """
    continuous = continuous_load_kw(consumers)
    if not continuous:
        return targets
    adjusted = dict(targets)
    for cid, kw in continuous.items():
        if cid not in adjusted:
            continue
        booked_kwh = kw * float(DEFAULT_DT_H) * int(credit_slots)
        adjusted[cid] = max(0.0, float(adjusted[cid]) - booked_kwh)
    return adjusted
