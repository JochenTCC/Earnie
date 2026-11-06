"""Baseline and matched-baseline horizon simulation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple, Sequence
from zoneinfo import ZoneInfo

import numpy as np

import config
from settings.flexible_consumers import flex_kw_lookup
from optimizer import battery as bat
from optimizer.consumer_power import power_limits_kw
from optimizer.milp_horizon import (
    aggregate_battery_params_for_load,
    coerce_battery_params_list,
)
from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.sim_chart_rows import (
    _chart_price_fields,
    _chart_row_slot_field,
    _finalize_chart_rows_for_display,
    _format_chart_uhrzeit,
)
from optimizer.targets import consumer_column_name


def _baseline_battery_params(
    battery_params: dict | list[dict] | None,
) -> dict:
    """House-load aggregate for baseline (multi-ESS list → singular dict)."""
    if battery_params is None:
        return config.get_battery_params()
    batteries = coerce_battery_params_list(battery_params)
    if not batteries:
        return config.get_battery_params()
    if len(batteries) == 1:
        return batteries[0]
    return aggregate_battery_params_for_load(batteries)


def _matched_baseline_profile_kw(row: dict, consumer: dict) -> float:
    """Flex kW used as matched-baseline *shape*.

    ``live_snapshot`` is the current meter reading, not a historical day profile.
    Scaling a full horizon target onto that single QH sample yields
    ``target / dt_h`` kW (factor 4 at ``DEFAULT_DT_H=0.25``) and inflated BL Ziel €.
    """
    if row.get("consumption_mode") == "live_snapshot":
        return 0.0
    return flex_kw_lookup(row.get("expected_flex_kw") or {}, consumer)


def build_matched_flex_kw_per_hour(
    optimization_matrix: list,
    consumer_targets_kwh: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
) -> list[dict[str, float]]:
    """
    Skaliert das historische Flex-Profil auf die aktuellen Horizont-Ziele (kWh).
    Zeitliche Form bleibt erhalten (auch unter Nennleistung); außerhalb des
    Ladezeitfensters null – wie im MILP. Live-Snapshot-Slots zählen nicht als Profil.
    """
    # Resolve via simulation facade so tests can monkeypatch
    # ``optimizer.simulation.config`` / ``consumer_charging_eligible_indices``.
    from optimizer import simulation as sim

    consumers_cfg = sim.config.get_flexible_consumers(optimizer_only=True)
    rows = optimization_matrix
    hour_count = len(rows)
    contexts = charging_contexts or {}
    schedule_indices = list(range(hour_count))

    eligible_by_consumer: dict[str, set[int]] = {}
    for consumer in consumers_cfg:
        cid = consumer["id"]
        eligible = sim.consumer_charging_eligible_indices(
            rows,
            consumer,
            schedule_indices,
            contexts.get(cid),
        )
        eligible_by_consumer[cid] = set(eligible)

    profile_sums: dict[str, float] = {c["id"]: 0.0 for c in consumers_cfg}
    for consumer in consumers_cfg:
        cid = consumer["id"]
        eligible = eligible_by_consumer[cid]
        for t, row in enumerate(rows):
            if t not in eligible:
                continue
            profile_sums[cid] += _matched_baseline_profile_kw(row, consumer)

    per_hour: list[dict[str, float]] = []
    for t, row in enumerate(rows):
        hour_flex: dict[str, float] = {}
        for consumer in consumers_cfg:
            cid = consumer["id"]
            target = float(consumer_targets_kwh.get(cid, 0.0) or 0.0)
            eligible = eligible_by_consumer[cid]
            if t not in eligible:
                hour_flex[cid] = 0.0
                continue
            eligible_count = len(eligible)
            profile_sum = profile_sums[cid]
            profile_val = _matched_baseline_profile_kw(row, consumer)
            if profile_sum > 1e-6:
                # target is kWh; profile_sum is Σ kW → scale so Σ(kW)*dt_h = target
                hour_flex[cid] = profile_val * (
                    target / (profile_sum * float(DEFAULT_DT_H))
                )
            elif target > 0 and eligible_count > 0:
                hour_flex[cid] = target / (eligible_count * float(DEFAULT_DT_H))
            else:
                hour_flex[cid] = 0.0
        per_hour.append(hour_flex)
    return per_hour


_ENERGY_EPSILON_KWH = 1e-3


class ShapedFlex(NamedTuple):
    """Reference flex of one window: kW per slot, and the consumers without a shape."""

    per_slot: list[dict[str, float]]
    no_shape_ids: list[str]


def _spread_with_power_cap(
    desired_kw: dict[int, float],
    eligible: list[int],
    max_kw: float,
) -> tuple[dict[int, float], float]:
    """Cap at ``max_kw``: excess moves to the next eligible slots, then to earlier ones.

    Returns ``(kw_by_slot, undelivered_kw)``; both passes keep the slot's own energy first.
    """
    out: dict[int, float] = {}
    carry = 0.0
    for t in eligible:
        wanted = desired_kw.get(t, 0.0) + carry
        out[t] = min(max_kw, wanted)
        carry = wanted - out[t]
    for t in reversed(eligible):
        if carry <= 0.0:
            break
        added = min(max_kw - out[t], carry)
        out[t] += added
        carry -= added
    return out, carry


def build_shaped_flex_kw_per_slot(
    slot_count: int,
    consumers: list[dict],
    targets_kwh: dict[str, float],
    shapes_kw: dict[str, list[float]],
    eligible_by_consumer: dict[str, list[int]],
) -> ShapedFlex:
    """Reference timing per consumer: its real shape, scaled to the target, capped at nominal.

    Target > 0 without shape energy in the eligible slots: nominal power from the start of
    the eligible slots ("switch on and run"), reported in ``no_shape_ids``. A target the
    eligible slots cannot deliver raises with the missing kWh. Pure.
    """
    dt_h = float(DEFAULT_DT_H)
    per_slot: list[dict[str, float]] = [{} for _ in range(slot_count)]
    no_shape_ids: list[str] = []
    for consumer in consumers:
        cid = consumer["id"]
        target = float(targets_kwh.get(cid, 0.0) or 0.0)
        eligible = eligible_by_consumer.get(cid, [])
        _, max_kw = power_limits_kw(consumer)
        shape_kw = shapes_kw.get(cid)
        shape_sum = sum(max(0.0, float(shape_kw[t])) for t in eligible) if shape_kw else 0.0
        if target <= 0.0:
            desired: dict[int, float] = {}
        elif shape_sum > 1e-6:
            scale = target / (shape_sum * dt_h)
            desired = {t: max(0.0, float(shape_kw[t])) * scale for t in eligible}
        else:
            no_shape_ids.append(str(cid))
            desired = {eligible[0]: target / dt_h} if eligible else {}
        delivered, undelivered_kw = _spread_with_power_cap(desired, eligible, max_kw)
        missing_kwh = undelivered_kw * dt_h if desired else target
        if missing_kwh > _ENERGY_EPSILON_KWH:
            raise ValueError(
                f"Referenz-Fenster: Verbraucher '{cid}' erreicht sein Ziel von {target:.3f} kWh "
                f"nicht, es fehlen {missing_kwh:.3f} kWh ({len(eligible)} zulässige Slots, "
                f"max. {max_kw:g} kW)."
            )
        for t in range(slot_count):
            per_slot[t][cid] = delivered.get(t, 0.0)
    return ShapedFlex(per_slot, no_shape_ids)


SURPLUS_CONSUMER_FIRST = "consumer_first"
SURPLUS_BATTERY_FIRST = "battery_first"
DEFAULT_RULE_PARAMS = {
    "lock_quantile": 0.75,
    "surplus_priority": SURPLUS_CONSUMER_FIRST,
}
_PRICE_EPSILON_CENT = 1e-9
_POWER_EPSILON_KW = 1e-9


class RuleBasedFlex(NamedTuple):
    """L2 flex of one window.

    ``no_shape_ids``: as in ``ShapedFlex``. ``no_published_block_ids``: cheapest-block
    consumers that kept their real timing because no start had all prices published.
    ``truncated_lock_slots``: slots whose price lock ran on a horizon cut by the data's end.
    """

    per_slot: list[dict[str, float]]
    no_shape_ids: list[str]
    no_published_block_ids: list[str]
    truncated_lock_slots: int


def _is_nonexistent_local_slot(slot_dt: datetime) -> bool:
    """True inside the spring DST gap of the planning timezone."""
    tz = ZoneInfo(config.get_planning_timezone())
    round_trip = slot_dt.replace(tzinfo=tz).astimezone(timezone.utc).astimezone(tz)
    return round_trip.replace(tzinfo=None) != slot_dt


def _last_published_stop(slot_dt: datetime) -> datetime:
    """End (exclusive) of the last day-ahead day published at ``slot_dt``."""
    from data.backtesting_prices import last_day_ahead_calendar_date

    return datetime.combine(
        last_day_ahead_calendar_date(slot_dt) + timedelta(days=1), datetime.min.time()
    )


def _lock_horizon_truncated(slot_dt: datetime, price_series: dict[datetime, float]) -> bool:
    step = timedelta(hours=float(DEFAULT_DT_H))
    return max(price_series) + step < _last_published_stop(slot_dt)


def available_slot_prices(
    slot_dt: datetime,
    price_series: dict[datetime, float],
) -> list[float]:
    """End-customer prices known at ``slot_dt``: the slot up to its last published day-ahead day.

    The range ends early only at the end of the series (spec § 4.2); a gap inside it raises.
    """
    stop = _last_published_stop(slot_dt)
    last_known = max(price_series)
    step = timedelta(hours=float(DEFAULT_DT_H))
    prices: list[float] = []
    current = slot_dt
    if current > last_known:
        raise ValueError(
            f"Referenz-Regeln: Kein Endkundenpreis für {current:%Y-%m-%d %H:%M}, "
            f"die Preisdaten enden {last_known:%Y-%m-%d %H:%M}."
        )
    while current < stop and current <= last_known:
        price = price_series.get(current)
        if price is not None:
            prices.append(float(price))
        elif not _is_nonexistent_local_slot(current):
            raise ValueError(
                f"Referenz-Regeln: Kein Endkundenpreis für {current:%Y-%m-%d %H:%M} "
                f"(nötig für die Preissperre um {slot_dt:%Y-%m-%d %H:%M})."
            )
        current += step
    return prices


def _price_locked(
    slot_dt: datetime,
    price_series: dict[datetime, float],
    quantile: float,
) -> bool:
    """Strictly above the quantile of the available prices: a flat tariff never locks."""
    prices = available_slot_prices(slot_dt, price_series)
    return prices[0] > float(np.quantile(prices, quantile)) + _PRICE_EPSILON_CENT


def _validated_rule_params(rule_params: dict) -> tuple[float, str]:
    quantile = float(rule_params["lock_quantile"])
    priority = rule_params["surplus_priority"]
    if not 0.0 <= quantile <= 1.0:
        raise ValueError(f"lock_quantile muss in [0, 1] liegen, nicht {quantile}.")
    if priority not in (SURPLUS_CONSUMER_FIRST, SURPLUS_BATTERY_FIRST):
        raise ValueError(f"Unbekannte surplus_priority {priority!r}.")
    return quantile, priority


def _is_ev_consumer(consumer: dict) -> bool:
    """House-profile EVs carry the type, config consumers only the charging schedule."""
    schedule = consumer.get("charging_schedule") or {}
    return consumer.get("type") == "ev" or bool(schedule.get("enabled"))


def _surplus_threshold_kw(consumer: dict, max_kw: float) -> float:
    """Start threshold: the configured minimum, else an EV modulates and others run on/off."""
    min_kw = float(consumer.get("min_power_kw") or 0.0)
    if min_kw > 0.0:
        return min_kw
    return 0.0 if _is_ev_consumer(consumer) else max_kw


@dataclass
class _RuleConsumer:
    """Deferral queue of one consumer: delivered + backlog + later planned = target."""

    cid: str
    planned_kw: list[float]
    eligible: list[int]
    max_kw: float
    price_lock: bool
    surplus: bool
    threshold_kw: float
    min_on_slots: int
    backlog_kwh: float = 0.0
    hold_slots: int = 0
    waits_for_surplus: bool = False

    def later_kwh(self, t: int) -> float:
        return sum(self.planned_kw[s] for s in self.eligible if s > t) * float(DEFAULT_DT_H)

    def draw(self, kwh: float, t: int) -> None:
        """Take delivered energy from the backlog, then from the back of the later profile."""
        from_backlog = min(kwh, self.backlog_kwh)
        self.backlog_kwh -= from_backlog
        missing = kwh - from_backlog
        dt_h = float(DEFAULT_DT_H)
        for s in reversed(self.eligible):
            if missing <= 0.0 or s <= t:
                break
            taken = min(missing, self.planned_kw[s] * dt_h)
            self.planned_kw[s] -= taken / dt_h
            missing -= taken

    def base_power_kw(self, t: int, locked: bool) -> float:
        """Planned energy and backlog unless locked, and never below the deadline's need."""
        dt_h = float(DEFAULT_DT_H)
        self.backlog_kwh += self.planned_kw[t] * dt_h
        self.planned_kw[t] = 0.0
        slots_after = sum(1 for s in self.eligible if s > t)
        later_kwh = self.later_kwh(t)
        needed_kw = max(
            0.0, (self.backlog_kwh + later_kwh - slots_after * self.max_kw * dt_h) / dt_h
        )
        wanted_kw = 0.0 if locked else self.backlog_kwh / dt_h
        power_kw = min(self.max_kw, max(wanted_kw, needed_kw))
        self.draw(power_kw * dt_h, t)
        return power_kw

    def surplus_extra_kw(self, t: int, power_kw: float, available_kw: float) -> float:
        """Extra power from the surplus; ``min_on_slots`` holds a started run."""
        if available_kw > _POWER_EPSILON_KW and available_kw >= self.threshold_kw:
            wanted_kw = min(self.max_kw, available_kw)
            self.hold_slots = self.min_on_slots - 1
        elif self.hold_slots > 0:
            wanted_kw = min(self.max_kw, max(self.threshold_kw, available_kw))
            self.hold_slots -= 1
        else:
            return 0.0
        dt_h = float(DEFAULT_DT_H)
        open_kwh = self.backlog_kwh + self.later_kwh(t)
        extra_kw = min(max(0.0, wanted_kw - power_kw), open_kwh / dt_h)
        self.draw(extra_kw * dt_h, t)
        return extra_kw


@dataclass
class SurplusRod:
    """Heating rod beside a fuel source in L2: on / off on the export left at the meter (spec § 4.3).

    It has no target and no deadline. ``heat_left_kwh``: heat it may still deliver per day (η = 1),
    the same caps as the MILP's, and like there it never runs part of a slot.
    """

    cid: str
    nominal_kw: float
    eligible: list[int]
    heat_left_kwh: dict[date, float]

    def run_kw(self, t: int, day: date, export_kw: float) -> float:
        heat_kwh = self.nominal_kw * float(DEFAULT_DT_H)
        if (
            t not in self.eligible
            or export_kw < self.nominal_kw - _POWER_EPSILON_KW
            or self.heat_left_kwh.get(day, 0.0) < heat_kwh - _ENERGY_EPSILON_KWH
        ):
            return 0.0
        self.heat_left_kwh[day] -= heat_kwh
        return self.nominal_kw


def _contiguous_runs(indices: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for index in indices:
        if runs and runs[-1][-1] == index - 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def _move_to_cheapest_block(
    planned_kw: list[float],
    eligible: list[int],
    matrix: list[dict],
    price_series: dict[datetime, float],
) -> bool:
    """Move the cycle to its cheapest start, judged on the prices published at window opening.

    Keeps the real start on a tie. Returns False when no start had all prices published.
    """
    from data.backtesting_prices import last_day_ahead_calendar_date

    active = [t for t in eligible if planned_kw[t] > 0.0]
    if not active:
        return True
    start, end = active[0], active[-1]
    cycle = planned_kw[start : end + 1]

    def block_cost(first: int) -> float:
        total = 0.0
        for offset, power_kw in enumerate(cycle):
            slot_dt = matrix[first + offset]["slot_datetime"]
            if slot_dt not in price_series:
                raise ValueError(
                    f"Referenz-Regeln: Kein Endkundenpreis für {slot_dt:%Y-%m-%d %H:%M} "
                    "(nötig für den günstigsten Block)."
                )
            total += power_kw * float(price_series[slot_dt])
        return total

    costs: dict[int, float] = {}
    for run in _contiguous_runs(eligible):
        published_until = last_day_ahead_calendar_date(matrix[run[0]]["slot_datetime"])
        for first in run[: max(0, len(run) - len(cycle) + 1)]:
            if matrix[first + len(cycle) - 1]["slot_datetime"].date() <= published_until:
                costs[first] = block_cost(first)
    if not costs:
        return False
    best = min(costs, key=lambda first: (costs[first], first))
    if start in costs and costs[start] <= costs[best] + _PRICE_EPSILON_CENT:
        return True
    for t in range(start, end + 1):
        planned_kw[t] = 0.0
    for offset, power_kw in enumerate(cycle):
        planned_kw[best + offset] = power_kw
    return True


def _rule_consumer(
    consumer: dict,
    planned_kw: list[float],
    eligible: list[int],
) -> _RuleConsumer:
    """Rules per consumer type (spec § 4.1). Cheapest block and fixed load run as planned."""
    _, max_kw = power_limits_kw(consumer)
    fixed_timing = bool(consumer.get("continuous_load") or consumer.get("generic_flex_window"))
    thermal = consumer.get("type") in ("thermal_annual", "thermal_rc")
    is_ev = _is_ev_consumer(consumer)
    return _RuleConsumer(
        cid=consumer["id"],
        planned_kw=planned_kw,
        eligible=eligible,
        max_kw=max_kw,
        price_lock=not fixed_timing and not is_ev,
        surplus=not fixed_timing and (is_ev or thermal),
        threshold_kw=_surplus_threshold_kw(consumer, max_kw),
        min_on_slots=max(1, int(consumer.get("min_on_quarterhours", 1) or 1)),
        waits_for_surplus=is_ev and not fixed_timing,
    )


def _export_left_kw(net_kw: float, soc: float, battery_params: dict) -> float:
    """What goes to the grid after the battery took its part of ``net_kw``."""
    _, batt_kw = bat.vendor_mode_step(soc, net_kw, battery_params, dt_h=DEFAULT_DT_H)
    return max(0.0, net_kw - max(0.0, batt_kw))


def _available_surplus_kw(
    consumer_id: str,
    net_before_flex_kw: float,
    slot_kw: dict[str, float],
    priority: str,
    soc: float,
    battery_params: dict,
) -> float:
    """Surplus the consumer sees, its own power included: before or after the battery."""
    if priority == SURPLUS_CONSUMER_FIRST:
        others_kw = sum(kw for cid, kw in slot_kw.items() if cid != consumer_id)
        return net_before_flex_kw - others_kw
    net_kw = net_before_flex_kw - sum(slot_kw.values())
    return slot_kw[consumer_id] + _export_left_kw(net_kw, soc, battery_params)


def build_rule_based_flex_kw_per_hour(
    matrix: list[dict],
    targets_kwh: dict[str, float],
    eligible_by_consumer: dict[str, list[int]],
    consumers: list[dict],
    shapes_kw: dict[str, list[float]],
    price_series: dict[datetime, float],
    rule_params: dict,
    *,
    book_indices: list[int],
    battery_params: dict,
    initial_soc: float,
    surplus_rods: Sequence[SurplusRod] = (),
) -> RuleBasedFlex:
    """L2: standard rules move the energy of the L1 profile, the total per consumer stays exact.

    Spec ``docs/dev/rule-based-reference.md`` § 4. ``price_series``: end-customer price per
    slot, up to the last published day-ahead day of the book's last slot or the end of the
    data. An EV waits for the surplus or its deadline; other consumers equal
    ``build_shaped_flex_kw_per_slot`` when no rule fires. ``surplus_rods`` come last in a slot
    and only take what would be exported, so they change neither the others nor the battery.
    A missing price inside the series or an undeliverable target raises.
    """
    quantile, priority = _validated_rule_params(rule_params)
    shaped = build_shaped_flex_kw_per_slot(
        len(matrix), consumers, targets_kwh, shapes_kw, eligible_by_consumer
    )
    no_published_block_ids: list[str] = []
    states: list[_RuleConsumer] = []
    for consumer in consumers:
        cid = consumer["id"]
        eligible = eligible_by_consumer.get(cid, [])
        planned_kw = [slot[cid] for slot in shaped.per_slot]
        if (
            consumer.get("generic_flex_window")
            and not consumer.get("continuous_load")
            and not _move_to_cheapest_block(planned_kw, eligible, matrix, price_series)
        ):
            no_published_block_ids.append(str(cid))
        states.append(_rule_consumer(consumer, planned_kw, eligible))

    dt_h = float(DEFAULT_DT_H)
    per_slot: list[dict[str, float]] = [
        {state.cid: 0.0 for state in states} | {rod.cid: 0.0 for rod in surplus_rods}
        for _ in range(len(matrix))
    ]
    soc = float(initial_soc)
    truncated_lock_slots = 0
    for t in book_indices:
        row = matrix[t]
        slot_kw = per_slot[t]
        locked: bool | None = None
        running: list[_RuleConsumer] = []
        for state in states:
            if t not in state.eligible:
                state.hold_slots = 0
                continue
            running.append(state)
            if state.price_lock and locked is None:
                locked = _price_locked(row["slot_datetime"], price_series, quantile)
                truncated_lock_slots += _lock_horizon_truncated(row["slot_datetime"], price_series)
            holds = state.waits_for_surplus or bool(state.price_lock and locked)
            slot_kw[state.cid] = state.base_power_kw(t, holds)
        net_before_flex_kw = float(row["expected_p_pv"]) - bat.effective_p_act(row, battery_params)
        for state in running:
            if state.surplus:
                available_kw = _available_surplus_kw(
                    state.cid, net_before_flex_kw, slot_kw, priority, soc, battery_params
                )
                slot_kw[state.cid] += state.surplus_extra_kw(t, slot_kw[state.cid], available_kw)
        for rod in surplus_rods:
            net_kw = net_before_flex_kw - sum(slot_kw.values())
            slot_kw[rod.cid] = rod.run_kw(t, row["date"], _export_left_kw(net_kw, soc, battery_params))
        soc, _ = bat.vendor_mode_step(
            soc, net_before_flex_kw - sum(slot_kw.values()), battery_params, dt_h=DEFAULT_DT_H
        )

    for state in states:
        target = float(targets_kwh.get(state.cid, 0.0) or 0.0)
        delivered = sum(slot[state.cid] for slot in per_slot) * dt_h
        if abs(target - delivered) > _ENERGY_EPSILON_KWH:
            raise ValueError(
                f"Referenz-Regeln: Verbraucher '{state.cid}' erreicht sein Ziel von "
                f"{target:.3f} kWh nicht, es fehlen {target - delivered:.3f} kWh."
            )
    return RuleBasedFlex(
        per_slot, shaped.no_shape_ids, no_published_block_ids, truncated_lock_slots
    )


def _simulate_single_hour_baseline(
    row: dict,
    sim_soc: float,
    battery_params: dict,
    flex_kw_override: dict[str, float] | None = None,
    steuerbefehl: str = "Baseline",
    baseload_kw_override: float | None = None,
    *,
    consumers: list[dict] | None = None,
) -> tuple[float, dict]:
    """Simuliert eine einzelne Stunde im Baseline-Pfad.

    ``consumers`` names the flex columns of the chart row (default: the live scenario's).
    """
    pv = row["expected_p_pv"]
    flex_kw = flex_kw_override if flex_kw_override is not None else (row.get("expected_flex_kw") or {})
    has_flex_profile = any(float(v or 0.0) > 0.0 for v in flex_kw.values())
    simulation_mode = row.get("consumption_mode") in ("logged_day", "profile_spec")
    if flex_kw_override is None and simulation_mode and not has_flex_profile:
        con = float(row.get("expected_p_total", row["expected_p_act"]) or 0.0)
        con = con + bat.standby_power_kw(battery_params)
        total_flex_power = 0.0
        flex_kw = {}
    elif baseload_kw_override is not None:
        con = float(baseload_kw_override) + bat.standby_power_kw(battery_params)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    else:
        con = bat.effective_p_act(row, battery_params)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    net_pv_surplus = pv - con - total_flex_power
    old_soc = sim_soc
    sim_soc, batt_action = bat.vendor_mode_step(
        old_soc, net_pv_surplus, battery_params, dt_h=DEFAULT_DT_H
    )
    p_grid = con + total_flex_power - pv + round(batt_action, 2)
    chart_row = {
        "Uhrzeit": _format_chart_uhrzeit(row),
        **_chart_row_slot_field(row),
        **_chart_price_fields(row),
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": con,
        "Geplante Batterie-Aktion (kW)": round(batt_action, 2),
        "Netzbezug (kW)": round(p_grid, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": steuerbefehl,
    }
    column_consumers = (
        consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)
    )
    for consumer in column_consumers:
        if flex_kw:
            chart_row[consumer_column_name(consumer)] = round(
                float(flex_kw.get(consumer["id"], 0.0) or 0.0), 2
            )
    return sim_soc, chart_row


def simulate_baseline_horizon(
    optimization_matrix: list,
    initial_soc: float,
    charging_contexts: dict[str, dict] | None = None,
    *,
    battery_params: dict | list[dict] | None = None,
) -> list:
    """Simuliert den 24h-Verlauf ohne Optimierung: Batterie folgt nur dem aktuellen PV-Überschuss."""
    chart_rows = []
    sim_soc = initial_soc
    battery_params = _baseline_battery_params(battery_params)
    for row in optimization_matrix:
        sim_soc, chart_row = _simulate_single_hour_baseline(row, sim_soc, battery_params)
        chart_rows.append(chart_row)
    _finalize_chart_rows_for_display(chart_rows, charging_contexts)
    return chart_rows


def _flex_kw_from_chart_row(chart_row: dict) -> dict[str, float]:
    """Flex-Leistungen je Verbraucher aus einer Simulationszeile."""
    return {
        consumer["id"]: float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
        for consumer in config.get_flexible_consumers(optimizer_only=True)
    }


def simulate_baseline_with_optimized_flex(
    optimization_matrix: list,
    optimized_rows: list,
    initial_soc: float,
    *,
    battery_params: dict | list[dict] | None = None,
) -> list:
    """
    Baseline-Batterie (nur PV-Überschuss), aber dieselbe stündliche Flex-Last wie optimiert.
    Für den stündlichen Kostenvergleich: gleiche Last, Unterschied nur Batterie/Netz.
    """
    battery_params = _baseline_battery_params(battery_params)
    sim_soc = initial_soc
    chart_rows: list[dict] = []
    for row, optimized_row in zip(optimization_matrix, optimized_rows):
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row,
            sim_soc,
            battery_params,
            flex_kw_override=_flex_kw_from_chart_row(optimized_row),
            steuerbefehl="Baseline (Ziel)",
            baseload_kw_override=float(
                optimized_row.get("Verbrauch-Prognose (kW)", row["expected_p_act"]) or 0.0
            ),
        )
        chart_rows.append(chart_row)
    return chart_rows


def simulate_matched_baseline_horizon(
    optimization_matrix: list,
    initial_soc: float,
    consumer_targets_kwh: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    *,
    battery_params: dict | list[dict] | None = None,
) -> list:
    """
    Baseline mit gleicher Flex-Energie wie die Optimierung,
    aber ohne Preis-Lastverschiebung – Batterie nur PV-Überschuss.
    """
    matched_flex = build_matched_flex_kw_per_hour(
        optimization_matrix,
        consumer_targets_kwh,
        charging_contexts,
    )
    chart_rows = []
    sim_soc = initial_soc
    battery_params = _baseline_battery_params(battery_params)
    for row, flex_kw in zip(optimization_matrix, matched_flex):
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row,
            sim_soc,
            battery_params,
            flex_kw_override=flex_kw,
            steuerbefehl="Baseline (Ziel)",
        )
        chart_rows.append(chart_row)
    _finalize_chart_rows_for_display(chart_rows, charging_contexts)
    return chart_rows
