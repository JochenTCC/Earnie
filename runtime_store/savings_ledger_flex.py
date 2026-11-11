"""Savings ledger v2: reference timing of the flex consumers for one SA-day (Ledger P9b).

Spec ``docs/dev/savings-ledger.md`` § 7, plan ``docs/dev/savings-ledger-v2-plan.md`` § 4.1.
Pure functions, no file I/O and no config reads: the caller passes the day's slot rows
(``LedgerState.slots``), the planning consumers, their reference shape per slot (the house
profile's model, ``savings_ledger_store.flex_day_inputs``, D8) and their windows
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

is_ev_consumer = _is_ev_consumer
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
# Heating rod beside a fuel heat source: 0 kWh in the shadow plant, its heat bought as fuel (plan § 4.4).
TIMING_FUEL = "fuel"
# EV: the day's energy at nominal power from the first plugged-in slot of the day (plan § 4.3, D5).
TIMING_PLUG_IN = "plug_in"
# EV that charged in a slot without logged plug state: keeps its logged timing (plan § 4.3).
TIMING_LOGGED_NO_PLUG_STATE = "logged_no_plug_state"

# Why a consumer with a meter and energy keeps its logged timing (``FlexRetiming.logged_reasons``).
REASON_NO_SHAPE_NO_WINDOW = "no_shape_no_window"
REASON_EXCEEDS_ELIGIBLE = "exceeds_eligible_slots"
REASON_NOT_CONFIGURED = "not_configured"
# No house profile, or a consumer model failed: no consumer is re-timed that day (not the
# windows instead: that would hide the broken configuration).
REASON_PROFILE_ERROR = "profile_error"
# Heating rod beside a fuel source without a fuel price (no ``fuel_credit_cent_per_kwh``): the
# shadow plant cannot buy its heat, so the rod keeps its logged timing (the MILP gives no credit either).
REASON_NO_FUEL_PRICE = "no_fuel_price"

# Where a filter's native window came from (row field ``flex_native_window_source``).
NATIVE_SOURCE_LOG = "log"
NATIVE_SOURCE_CONFIG = "config"

# Same tolerance as the builder's undelivered check (``sim_baseline._ENERGY_EPSILON_KWH``).
_ENERGY_EPSILON_KWH = 1e-3
_SHAPE_EPSILON = 1e-6


@dataclass(frozen=True)
class ConsumerWindows:
    """Windows of one consumer as indices into the day's slot rows (``None``: not configured).

    ``enable_slots``: the window the MILP keeps the consumer in (``thermal_flex_window`` of a
    thermal consumer or heating rod, ``generic_flex_window``). It bounds the reference and is
    its flat shape when there is no profile.
    ``native_slots``: the filter's native run. Flat shape when there is no profile; it does not
    bound the reference, so energy beyond the native run continues in the slots after it.
    ``native_source``: where the native run came from, ``log`` (the window the cycles used) or
    ``config`` (``filter_schedule.config_fallback``); ``None`` without native window.
    """

    enable_slots: frozenset[int] | None
    native_slots: frozenset[int] | None
    native_source: str | None = None


@dataclass(frozen=True)
class FlexDayInputs:
    """What the day replay needs besides the slot rows (``retime_flex_day``).

    ``profiles_kw``: the house profile's model per consumer and slot row (D8); ``None`` when there
    is no house profile or a model failed (``REASON_PROFILE_ERROR``).
    """

    consumers: list[dict]
    profiles_kw: dict[str, list[float]] | None
    windows: dict[str, ConsumerWindows]


@dataclass(frozen=True)
class FlexRetiming:
    """Reference flex of one SA-day.

    ``per_slot_kw``: kW per consumer for every slot row (zero in skipped slots), the
    ``flex_retimed`` of the shadow plant. ``timing``: ``flex_timing`` per consumer.
    ``logged_reasons``: consumers with timing ``logged`` and why. ``delivered_kwh``: energy per
    consumer over the counted slots, equal to the sum of ``per_slot_kw`` · dt except for a rod on
    fuel (timing ``fuel``), which is zero in ``per_slot_kw``.
    ``fuel_eur_per_slot``: fuel the shadow plant buys per slot row for the heat of those rods
    (rod kWh · ``fuel_credit_cent_per_kwh``, the MILP's credit). ``fuel_kwh``: that fuel in kWh
    (rod kWh ÷ the heat source's efficiency).
    """

    per_slot_kw: list[dict[str, float]]
    timing: dict[str, str]
    logged_reasons: dict[str, str]
    delivered_kwh: dict[str, float]
    fuel_eur_per_slot: list[float]
    fuel_kwh: float


def consumer_windows(
    consumer: dict,
    slot_starts_local: list[datetime],
    *,
    logged_native: dict[str, float] | None,
) -> ConsumerWindows:
    """Windows of ``consumer`` over the slots (plan § 4.1).

    Thermal consumers and heating rods: ``thermal_flex_window``; any consumer with a
    ``generic_flex_window``: that window (the MILP's slot rules, hour of the slot inside the
    window). Filter (``filter_schedule`` enabled): ``logged_native`` (``native_start_hour``,
    ``native_duration_hours`` the cycles used), else start and duration from
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
    source: str | None = None
    if filter_schedule_enabled(consumer):
        if logged_native is not None:
            start = logged_native["native_start_hour"]
            duration = logged_native["native_duration_hours"]
            source = NATIVE_SOURCE_LOG
        else:
            fallback = (consumer.get("filter_schedule") or {}).get("config_fallback") or {}
            start = fallback.get("native_start_hour")
            duration = fallback.get("native_duration_hours")
            source = NATIVE_SOURCE_CONFIG if start is not None and duration is not None else None
        if start is not None and duration is not None:
            native = frozenset(
                i
                for i, moment in enumerate(slot_starts_local)
                if slot_in_native_window(moment, float(start), float(duration))
            )
    return ConsumerWindows(
        enable_slots=frozenset(enable) if enable is not None else None,
        native_slots=native,
        native_source=source,
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
    native = windows.native_slots
    if native is not None and any(i in native for i in bound):
        return TIMING_NATIVE_WINDOW, bound, [1.0 if i in native else 0.0 for i in range(n)]
    if profile_kw is not None and sum(max(0.0, profile_kw[i]) for i in bound) > _SHAPE_EPSILON:
        return TIMING_PROFILE, bound, list(profile_kw)
    if windows.enable_slots is not None and bound:
        enabled = set(bound)
        return TIMING_ENABLE_WINDOW, bound, [1.0 if i in enabled else 0.0 for i in range(n)]
    return None


def _ev_plugged_slots(rows: list[dict[str, Any]], counted: list[int], cid: str) -> list[int] | None:
    """Counted slots an EV could charge in: plugged in, or charged (the plug state is read at the
    cycle's start, so a car plugged in during the slot shows ``False`` there). ``None`` when a slot
    it charged in has no plug state."""
    eligible: list[int] = []
    for i in counted:
        charged = float((rows[i].get("flex_delivered_kwh") or {}).get(cid, 0.0)) > 0.0
        state = (rows[i].get("plugged_in") or {}).get(cid)
        if charged and state is None:
            return None
        if charged or state is True:
            eligible.append(i)
    return eligible


def retime_flex_day(
    slot_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    consumers: list[dict],
    profiles_kw: dict[str, list[float]] | None,
    windows: dict[str, ConsumerWindows],
    *,
    dt_h: float,
) -> FlexRetiming:
    """Reference timing (``flex_retimed``) of one SA-day from its slot rows.

    Per configured consumer, in this order:

    - no ``flex_delivered_kwh`` key in any counted slot: no own meter, ``logged_no_meter``;
    - no energy over the counted slots: ``no_energy``, logged timing (nothing to place);
    - an EV: ``plug_in``, the day's energy at nominal power from the first plugged-in slot of
      the day over the slots it was plugged in or charged in (slot rows' ``plugged_in``); a
      charging slot without plug state keeps the logged timing (``logged_no_plug_state``);
    - heating rod beside a fuel heat source (``parent_heat_electric`` false): ``fuel``, zero in the
      shadow plant and its delivered kWh bought as fuel in the slot it ran in; without a fuel
      price logged timing (``no_fuel_price``). Beside an electric source the rod is ordinary;
    - ``profiles_kw`` ``None`` (no house profile or a failed model): logged timing (``profile_error``);
    - filter native window with a counted slot: ``native_window`` (flat shape there, the rest
      of the day eligible): the device's own schedule comes before its model;
    - model with energy in the counted slots of its enable window: ``profile``;
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
    fuel_eur = [0.0] * n
    fuel_kwh = 0.0

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
        profile = profiles_kw.get(cid) if profiles_kw is not None else None
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
        if energy <= _ENERGY_EPSILON_KWH:
            keep_logged(cid, TIMING_NO_ENERGY)
            continue
        if _is_ev_consumer(consumer):
            eligible = _ev_plugged_slots(rows, counted, cid)
            if eligible is None:
                keep_logged(cid, TIMING_LOGGED_NO_PLUG_STATE)
                continue
            _, max_kw = power_limits_kw(consumer)
            if energy > len(eligible) * max_kw * dt_h + _ENERGY_EPSILON_KWH:
                keep_logged(cid, TIMING_LOGGED, REASON_EXCEEDS_ELIGIBLE)
                continue
            # one unit at plug-in: the builder caps it at nominal and carries the rest forward
            shape = [1.0 if i == eligible[0] else 0.0 for i in range(n)]
            shaped = build_shaped_flex_kw_per_slot(n, [consumer], {cid: energy}, {cid: shape}, {cid: eligible})
            for i in range(n):
                per_slot[i][cid] = shaped.per_slot[i][cid]
            timing[cid] = TIMING_PLUG_IN
            continue
        if is_heating_rod_consumer(consumer) and not consumer["parent_heat_electric"]:
            credit = consumer.get("fuel_credit_cent_per_kwh")
            if credit is None:
                keep_logged(cid, TIMING_LOGGED, REASON_NO_FUEL_PRICE)
                continue
            efficiency = float(consumer["parent_heat_efficiency"])
            for i in range(n):
                per_slot[i][cid] = 0.0
                rod_kwh = float((rows[i].get("flex_delivered_kwh") or {}).get(cid, 0.0)) if rows[i]["counted"] else 0.0
                fuel_eur[i] += rod_kwh * float(credit) / 100.0
                fuel_kwh += rod_kwh / efficiency
            timing[cid] = TIMING_FUEL
            continue
        if profiles_kw is None:
            keep_logged(cid, TIMING_LOGGED, REASON_PROFILE_ERROR)
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
    return FlexRetiming(per_slot, timing, reasons, delivered, fuel_eur, fuel_kwh)
