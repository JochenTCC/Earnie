"""Savings ledger v2: reference timing of the flex consumers for one SA-day (Ledger P9b).

Spec ``docs/dev/savings-ledger.md`` § 7, plan ``docs/dev/savings-ledger-v2-plan.md`` § 4.1.
Pure functions, no file I/O and no config reads: the caller passes the day's slot rows
(``LedgerState.slots``), the planning consumers, their profile kW per slot
(``data.profile_manager.load_flexible_consumer_slot_profiles_strict``) and their windows
(``consumer_windows``).

``retime_flex_day`` places the energy each consumer delivered in the counted slots of the
day in the timing it has without Earnie, over the counted slots only, so the day's energy
per consumer is equal on both sides whatever the coverage. A consumer that cannot be
re-timed keeps its logged timing for that day, and the reason is returned with it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from optimizer.consumer_power import power_limits_kw
from optimizer.filter_context import filter_schedule_enabled, slot_in_native_window
from optimizer.generic_flex_context import consumer_generic_eligible_indices, generic_flex_window
from optimizer.sim_baseline import _is_ev_consumer, build_shaped_flex_kw_per_slot
from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.thermal_flex_context import (
    consumer_thermal_eligible_indices,
    is_heating_rod_consumer,
    is_thermal_flex_consumer,
    thermal_flex_window,
)

# ``flex_timing`` per consumer (row format, plan § 4.2).
TIMING_PROFILE = "profile"
TIMING_NATIVE_WINDOW = "native_window"
TIMING_ENABLE_WINDOW = "enable_window"
TIMING_LOGGED = "logged"
TIMING_LOGGED_NO_METER = "logged_no_meter"
TIMING_NO_ENERGY = "no_energy"

# Why a consumer with a meter and energy keeps its logged timing (``FlexRetiming.logged_reasons``).
REASON_NO_SHAPE_NO_WINDOW = "no_shape_no_window"
REASON_EXCEEDS_ELIGIBLE = "exceeds_eligible_slots"
REASON_NOT_CONFIGURED = "not_configured"
# The EV rule (from plug-in, plan § 4.3) is step Ledger P10a; until then an EV keeps its timing.
REASON_EV_RULE_MISSING = "ev_rule_missing"

# Same tolerance as the builder's undelivered check (``sim_baseline._ENERGY_EPSILON_KWH``).
_ENERGY_EPSILON_KWH = 1e-3
_SHAPE_EPSILON = 1e-6


@dataclass(frozen=True)
class ConsumerWindows:
    """Windows of one consumer as indices into the day's slot rows (``None``: not configured).

    ``enable_slots``: the window the MILP keeps the consumer in (``thermal_flex_window`` of a
    thermal consumer or heating rod, ``generic_flex_window``). It bounds the reference and is
    its flat shape when there is no profile.
    ``native_slots``: the filter's native run (``filter_schedule.config_fallback``). Flat shape
    when there is no profile; it does not bound the reference, so energy beyond the native run
    continues in the slots after it.
    """

    enable_slots: frozenset[int] | None
    native_slots: frozenset[int] | None


@dataclass(frozen=True)
class FlexRetiming:
    """Reference flex of one SA-day.

    ``per_slot_kw``: kW per consumer for every slot row (zero in skipped slots), the
    ``flex_retimed`` of the shadow plant. ``timing``: ``flex_timing`` per consumer.
    ``logged_reasons``: consumers with timing ``logged`` and why. ``delivered_kwh``: energy per
    consumer over the counted slots, equal to the sum of ``per_slot_kw`` · dt.
    """

    per_slot_kw: list[dict[str, float]]
    timing: dict[str, str]
    logged_reasons: dict[str, str]
    delivered_kwh: dict[str, float]


def consumer_windows(consumer: dict, slot_starts_local: list[datetime]) -> ConsumerWindows:
    """Windows of ``consumer`` over the slots, from its planning configuration (plan § 4.1).

    Thermal consumers and heating rods: ``thermal_flex_window``; any consumer with a
    ``generic_flex_window``: that window (the MILP's slot rules, hour of the slot inside the
    window). Filter (``filter_schedule`` enabled): native start and duration from
    ``config_fallback``. ``slot_starts_local`` are naive local wall-clock times.
    """
    for moment in slot_starts_local:
        if moment.tzinfo is not None:
            raise ValueError("savings ledger flex: slot starts must be naive local times")
    pseudo = [{"slot_datetime": moment} for moment in slot_starts_local]
    every = list(range(len(pseudo)))
    enable: set[int] | None = None
    if (is_thermal_flex_consumer(consumer) or is_heating_rod_consumer(consumer)) and thermal_flex_window(
        consumer
    ):
        enable = set(consumer_thermal_eligible_indices(pseudo, consumer, every))
    if generic_flex_window(consumer):
        generic = set(consumer_generic_eligible_indices(pseudo, consumer, every))
        enable = generic if enable is None else enable & generic
    native: frozenset[int] | None = None
    if filter_schedule_enabled(consumer):
        fallback = (consumer.get("filter_schedule") or {}).get("config_fallback") or {}
        start = fallback.get("native_start_hour")
        duration = fallback.get("native_duration_hours")
        if start is not None and duration is not None:
            native = frozenset(
                i
                for i, moment in enumerate(slot_starts_local)
                if slot_in_native_window(moment, float(start), float(duration))
            )
    return ConsumerWindows(
        enable_slots=frozenset(enable) if enable is not None else None,
        native_slots=native,
    )


def _logged_kw(rows: list[dict[str, Any]], cid: str, dt_h: float) -> list[float]:
    return [
        float((row.get("flex_delivered_kwh") or {}).get(cid, 0.0)) / dt_h if row["counted"] else 0.0
        for row in rows
    ]


def _reference_shape(
    n: int,
    counted: list[int],
    profile_kw: list[float] | None,
    windows: ConsumerWindows,
) -> tuple[str, list[int], list[float]] | None:
    """``(timing, eligible, shape_kw)`` of a consumer, or ``None`` without shape and window."""
    if windows.enable_slots is not None:
        bound = [i for i in counted if i in windows.enable_slots]
    else:
        bound = list(counted)
    if profile_kw is not None and sum(max(0.0, profile_kw[i]) for i in bound) > _SHAPE_EPSILON:
        return TIMING_PROFILE, bound, list(profile_kw)
    native = windows.native_slots
    if native is not None and any(i in native for i in bound):
        return TIMING_NATIVE_WINDOW, bound, [1.0 if i in native else 0.0 for i in range(n)]
    if windows.enable_slots is not None and bound:
        enabled = set(bound)
        return TIMING_ENABLE_WINDOW, bound, [1.0 if i in enabled else 0.0 for i in range(n)]
    return None


def retime_flex_day(
    slot_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    consumers: list[dict],
    profiles_kw: dict[str, list[float]],
    windows: dict[str, ConsumerWindows],
    *,
    dt_h: float,
) -> FlexRetiming:
    """Reference timing (``flex_retimed``) of one SA-day from its slot rows.

    Per configured consumer, in this order:

    - no ``flex_delivered_kwh`` key in any counted slot: no own meter, ``logged_no_meter``;
    - an EV: logged timing (``ev_rule_missing``) until the plug-in rule exists (P10a);
    - no energy over the counted slots: ``no_energy``, logged timing (nothing to place);
    - profile with energy in the counted slots of its enable window: ``profile``;
    - filter native window with a counted slot: ``native_window`` (flat shape there, the rest
      of the day eligible);
    - enable window with a counted slot: ``enable_window`` (flat over it);
    - else logged timing (``no_shape_no_window``). Energy above what the eligible slots hold at
      nominal power also keeps the logged timing (``exceeds_eligible_slots``).

    A consumer in ``flex_delivered_kwh`` that is not configured keeps its logged timing
    (``not_configured``). ``profiles_kw`` holds the profile kW per slot row of each consumer
    with a profile (no key: no profile); ``windows`` must hold every configured consumer.
    """
    if abs(float(dt_h) - float(DEFAULT_DT_H)) > 1e-12:
        raise ValueError(f"savings ledger flex: the shape builder runs on {DEFAULT_DT_H} h slots, got {dt_h}")
    rows = list(slot_rows)
    n = len(rows)
    counted = [i for i, row in enumerate(rows) if row["counted"]]
    per_slot: list[dict[str, float]] = [{} for _ in range(n)]
    timing: dict[str, str] = {}
    reasons: dict[str, str] = {}
    delivered: dict[str, float] = {}

    def keep_logged(cid: str, label: str, reason: str | None = None) -> None:
        for i, kw in enumerate(_logged_kw(rows, cid, dt_h)):
            per_slot[i][cid] = kw
        timing[cid] = label
        if reason is not None:
            reasons[cid] = reason

    configured: set[str] = set()
    for consumer in consumers:
        cid = str(consumer["id"])
        configured.add(cid)
        if cid not in windows:
            raise ValueError(f"savings ledger flex: no windows for consumer '{cid}'")
        profile = profiles_kw.get(cid)
        if profile is not None and len(profile) != n:
            raise ValueError(
                f"savings ledger flex: profile of '{cid}' has {len(profile)} values for {n} slot rows"
            )
        energy = sum(float(rows[i].get("flex_delivered_kwh", {}).get(cid, 0.0)) for i in counted)
        delivered[cid] = energy
        has_meter = any(cid in (rows[i].get("flex_delivered_kwh") or {}) for i in counted)
        if not has_meter:
            keep_logged(cid, TIMING_LOGGED_NO_METER)
            continue
        if _is_ev_consumer(consumer):
            keep_logged(cid, TIMING_LOGGED, REASON_EV_RULE_MISSING)
            continue
        if energy <= _ENERGY_EPSILON_KWH:
            keep_logged(cid, TIMING_NO_ENERGY)
            continue
        reference = _reference_shape(n, counted, profile, windows[cid])
        if reference is None:
            keep_logged(cid, TIMING_LOGGED, REASON_NO_SHAPE_NO_WINDOW)
            continue
        label, eligible, shape = reference
        _, max_kw = power_limits_kw(consumer)
        if energy > len(eligible) * max_kw * dt_h + _ENERGY_EPSILON_KWH:
            keep_logged(cid, TIMING_LOGGED, REASON_EXCEEDS_ELIGIBLE)
            continue
        shaped = build_shaped_flex_kw_per_slot(n, [consumer], {cid: energy}, {cid: shape}, {cid: eligible})
        if shaped.no_shape_ids:
            raise AssertionError(f"savings ledger flex: '{cid}' reached the builder without a shape")
        for i in range(n):
            per_slot[i][cid] = shaped.per_slot[i][cid]
        timing[cid] = label

    extra = sorted(
        {cid for i in counted for cid in (rows[i].get("flex_delivered_kwh") or {})} - configured
    )
    for cid in extra:
        delivered[cid] = sum(float(rows[i]["flex_delivered_kwh"].get(cid, 0.0)) for i in counted)
        keep_logged(cid, TIMING_LOGGED, REASON_NOT_CONFIGURED)
    return FlexRetiming(per_slot, timing, reasons, delivered)
