"""Live-history attribution: consumer PV/battery/grid mix and grid-only costs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

import config
from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start
from runtime_store import optimization_history
from runtime_store.history_timeline import (
    _chart_battery_kw_from_snapshot,
    _consumer_kw_from_entry,
    _parse_completed_at,
    _power_kw_from_entry,
)
from ui.flow_balance_allocate import allocate_slot_flows

BASELOAD_ID = "baseload"
BASELOAD_LABEL = "Grundlast"
SLOT_DURATION_HOURS = QUARTER_HOUR_MINUTES / 60.0


def cost_analysis_consumers() -> list[dict[str, Any]]:
    """Optimizer flex plus earnie_role=manual appliances (Chart-1 stack parity)."""
    from optimizer.appliance_schedule import appliance_as_chart_consumer

    flex = list(config.get_flexible_consumers(optimizer_only=True))
    flex_ids = {str(c["id"]) for c in flex}
    manuals = [
        appliance_as_chart_consumer(appliance)
        for appliance in config.get_appliances()
        if str(appliance["id"]) not in flex_ids
    ]
    return [*flex, *manuals]


def _is_manual_chart_consumer(consumer: Mapping[str, Any]) -> bool:
    from optimizer.appliance_schedule import is_manual_appliance_chart_consumer

    return is_manual_appliance_chart_consumer(consumer)


@dataclass(frozen=True)
class ConsumerSlotShare:
    """Attributed energy and point-of-use cost for one load share in a slot."""

    consumer_id: str
    load_kw: float
    pv_kwh: float
    battery_kwh: float
    grid_kwh: float
    cost_euro: float


@dataclass(frozen=True)
class CostAnalysisSlot:
    """One present history slot with house flows and per-consumer shares."""

    slot_start: datetime
    price_cent: float
    pv_kw: float
    load_kw: float
    shares: tuple[ConsumerSlotShare, ...]
    battery_charge_kwh: float
    battery_discharge_kwh: float
    charge_from_pv_kwh: float
    charge_from_grid_kwh: float
    discharge_to_load_kwh: float
    export_from_battery_kwh: float
    house_grid_cost_euro: float


@dataclass(frozen=True)
class PeriodTotals:
    """Rough energy and cost rollup for a time window."""

    energy_kwh: float
    pv_kwh: float
    battery_kwh: float
    grid_kwh: float
    cost_euro: float
    by_consumer: Mapping[str, ConsumerSlotShare]
    battery_charge_kwh: float
    battery_discharge_kwh: float
    charge_from_pv_kwh: float
    charge_from_grid_kwh: float
    discharge_to_load_kwh: float
    export_from_battery_kwh: float
    slot_count: int


@dataclass(frozen=True)
class CostAnalysisSeries:
    """Attributed slots from the live optimization history log."""

    slots: tuple[CostAnalysisSlot, ...]
    consumer_labels: Mapping[str, str]
    data_start: datetime | None
    data_end: datetime | None


def attribute_load_shares(
    *,
    load_by_id: Mapping[str, float],
    pv_to_load: float,
    grid_to_load: float,
    discharge_to_load: float,
    price_cent: float,
    dt_hours: float = SLOT_DURATION_HOURS,
) -> tuple[ConsumerSlotShare, ...]:
    """
    Pro-rata house load mix onto consumers (option I: only grid kWh costs €).

    PV and battery discharge shares are attributed for visualization but cost 0 €.
    """
    positive = {
        cid: max(float(kw), 0.0)
        for cid, kw in load_by_id.items()
        if float(kw) > 1e-12
    }
    total = sum(positive.values())
    if total <= 1e-12:
        return ()

    shares: list[ConsumerSlotShare] = []
    for cid, load_kw in positive.items():
        fraction = load_kw / total
        pv_kwh = fraction * max(pv_to_load, 0.0) * dt_hours
        battery_kwh = fraction * max(discharge_to_load, 0.0) * dt_hours
        grid_kwh = fraction * max(grid_to_load, 0.0) * dt_hours
        cost_euro = grid_kwh * float(price_cent) / 100.0
        shares.append(
            ConsumerSlotShare(
                consumer_id=cid,
                load_kw=load_kw,
                pv_kwh=round(pv_kwh, 6),
                battery_kwh=round(battery_kwh, 6),
                grid_kwh=round(grid_kwh, 6),
                cost_euro=round(cost_euro, 6),
            )
        )
    return tuple(shares)


def build_slot_from_powers(
    *,
    slot_start: datetime,
    price_cent: float,
    pv_kw: float,
    load_by_id: Mapping[str, float],
    battery_charge_kw: float,
    battery_discharge_kw: float,
    grid_import_kw: float,
    grid_export_kw: float,
    dt_hours: float = SLOT_DURATION_HOURS,
) -> CostAnalysisSlot:
    """Allocate house flows and attribute load shares for one slot."""
    load_kw = sum(max(float(v), 0.0) for v in load_by_id.values())
    flows = allocate_slot_flows(
        pv=max(float(pv_kw), 0.0),
        load_kw=load_kw,
        battery_charge=max(float(battery_charge_kw), 0.0),
        battery_discharge=max(float(battery_discharge_kw), 0.0),
        grid_import=max(float(grid_import_kw), 0.0),
        grid_export=max(float(grid_export_kw), 0.0),
    )
    shares = attribute_load_shares(
        load_by_id=load_by_id,
        pv_to_load=flows.pv_to_load,
        grid_to_load=flows.grid_to_load,
        discharge_to_load=flows.discharge_to_load,
        price_cent=price_cent,
        dt_hours=dt_hours,
    )
    house_grid_cost = flows.grid_to_load * dt_hours * float(price_cent) / 100.0
    return CostAnalysisSlot(
        slot_start=slot_start,
        price_cent=float(price_cent),
        pv_kw=max(float(pv_kw), 0.0),
        load_kw=load_kw,
        shares=shares,
        battery_charge_kwh=round(flows.charge_kw * dt_hours, 6),
        battery_discharge_kwh=round(flows.discharge_kw * dt_hours, 6),
        charge_from_pv_kwh=round(flows.charge_from_pv * dt_hours, 6),
        charge_from_grid_kwh=round(flows.charge_from_grid * dt_hours, 6),
        discharge_to_load_kwh=round(flows.discharge_to_load * dt_hours, 6),
        export_from_battery_kwh=round(flows.export_from_battery * dt_hours, 6),
        house_grid_cost_euro=round(house_grid_cost, 6),
    )


def _manual_kw_from_schedules(
    slot_start: datetime,
    consumer: Mapping[str, Any],
    schedules: Mapping[str, Mapping[str, Any]] | None,
) -> float | None:
    """Planned manual appliance kW for slot (Chart-1 peel); None if not scheduled."""
    if not schedules:
        return None
    from optimizer.appliance_schedule import appliance_kw_for_slot

    by_id = appliance_kw_for_slot(
        slot_start,
        dict(schedules),
        appliances_by_id={str(consumer["id"]): dict(consumer)},
    )
    kw = by_id.get(str(consumer["id"]))
    if kw is None or float(kw) <= 1e-12:
        return None
    return max(float(kw), 0.0)


def _measured_flex_kw(entry: dict[str, Any], consumer: Mapping[str, Any]) -> float | None:
    """Return measured kW only when the consumer id is present in the log maps."""
    from runtime_store.history_timeline import _flex_dict_has_consumer
    from settings.flexible_consumers import flex_kw_lookup

    snapshot = entry.get("consumption_snapshot") or {}
    flex_kw = snapshot.get("flex_kw") or {}
    if _flex_dict_has_consumer(flex_kw, dict(consumer)):
        return max(float(flex_kw_lookup(flex_kw, dict(consumer))), 0.0)
    live = entry.get("flex_live_kw") or {}
    if _flex_dict_has_consumer(live, dict(consumer)):
        return max(float(flex_kw_lookup(live, dict(consumer))), 0.0)
    return None


def _load_by_id_from_entry(
    entry: dict[str, Any],
    consumers: Sequence[Mapping[str, Any]],
    *,
    slot_start: datetime,
    schedules: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, float]:
    """Baseload + measured flex + manuals (measured or schedule peel from baseload)."""
    _, baseload, _ = _power_kw_from_entry(entry)
    baseload_kw = max(float(baseload), 0.0)
    loads: dict[str, float] = {}
    for consumer in consumers:
        cid = str(consumer["id"])
        if _is_manual_chart_consumer(consumer):
            measured = _measured_flex_kw(entry, consumer)
            if measured is not None:
                if measured > 1e-12:
                    loads[cid] = measured
                continue
            scheduled = _manual_kw_from_schedules(slot_start, consumer, schedules)
            if scheduled is None:
                continue
            loads[cid] = scheduled
            baseload_kw = max(0.0, baseload_kw - scheduled)
            continue
        flex_kw = _consumer_kw_from_entry(entry, dict(consumer))
        if flex_kw is None:
            continue
        loads[cid] = max(float(flex_kw), 0.0)
    loads[BASELOAD_ID] = baseload_kw
    return loads


def _grid_import_export_kw(entry: dict[str, Any], load_kw: float, pv_kw: float) -> tuple[float, float]:
    snapshot = entry.get("consumption_snapshot") or {}
    grid_raw = snapshot.get("grid_kw")
    if grid_raw is not None:
        grid = float(grid_raw)
        return max(grid, 0.0), max(-grid, 0.0)
    # Fallback balance without battery when snapshot lacks grid
    net = load_kw - pv_kw
    return max(net, 0.0), max(-net, 0.0)


def _battery_charge_discharge_kw(entry: dict[str, Any]) -> tuple[float, float]:
    snapshot = entry.get("consumption_snapshot") or {}
    ist = _chart_battery_kw_from_snapshot(snapshot)
    if ist is not None:
        return max(ist, 0.0), max(-ist, 0.0)
    _, _, battery_plan = _power_kw_from_entry(entry)
    plan = float(battery_plan)
    return max(plan, 0.0), max(-plan, 0.0)


def slot_from_replay_entry(
    entry: dict[str, Any],
    slot_start: datetime,
    *,
    consumers: Sequence[Mapping[str, Any]] | None = None,
    schedules: Mapping[str, Mapping[str, Any]] | None = None,
) -> CostAnalysisSlot:
    """Build one attributed slot from a productivity-log entry."""
    flex = list(consumers) if consumers is not None else cost_analysis_consumers()
    pv_kw, _, _ = _power_kw_from_entry(entry)
    snapshot = entry.get("consumption_snapshot") or {}
    if snapshot.get("pv_kw") is not None:
        pv_kw = float(snapshot["pv_kw"])
    load_by_id = _load_by_id_from_entry(
        entry,
        flex,
        slot_start=slot_start,
        schedules=schedules,
    )
    load_kw = sum(load_by_id.values())
    charge_kw, discharge_kw = _battery_charge_discharge_kw(entry)
    grid_import, grid_export = _grid_import_export_kw(entry, load_kw, pv_kw)
    price = float(entry.get("market_price_cent", 0.0) or 0.0)
    return build_slot_from_powers(
        slot_start=slot_start,
        price_cent=price,
        pv_kw=pv_kw,
        load_by_id=load_by_id,
        battery_charge_kw=charge_kw,
        battery_discharge_kw=discharge_kw,
        grid_import_kw=grid_import,
        grid_export_kw=grid_export,
    )


def _entries_by_slot(entries: Sequence[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    by_slot: dict[datetime, dict[str, Any]] = {}
    for entry in entries:
        completed = _parse_completed_at(entry)
        if completed is None:
            continue
        slot = quarter_hour_slot_start(completed)
        existing = by_slot.get(slot)
        if existing is None:
            by_slot[slot] = entry
            continue
        existing_at = _parse_completed_at(existing)
        if existing_at is None or completed > existing_at:
            by_slot[slot] = entry
    return by_slot


def _consumer_labels(consumers: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    labels = {BASELOAD_ID: BASELOAD_LABEL}
    for consumer in consumers:
        cid = str(consumer["id"])
        labels[cid] = str(consumer.get("name") or consumer.get("label") or cid)
    return labels


def build_cost_analysis_series(
    *,
    now: datetime | None = None,
    consumers: Sequence[Mapping[str, Any]] | None = None,
) -> CostAnalysisSeries | None:
    """Load all present history slots and attribute costs (live log only)."""
    earliest = optimization_history.earliest_replay_completed_at()
    if earliest is None:
        return None
    end = quarter_hour_slot_start(now)
    flex = list(consumers) if consumers is not None else cost_analysis_consumers()
    from runtime_store.appliance_schedules import load_schedules

    schedules = load_schedules()
    entries = optimization_history.load_replay_entries_between(earliest, end)
    if not entries:
        return None
    by_slot = _entries_by_slot(entries)
    if not by_slot:
        return None
    slots = tuple(
        slot_from_replay_entry(
            entry,
            slot_start,
            consumers=flex,
            schedules=schedules,
        )
        for slot_start, entry in sorted(by_slot.items())
    )
    return CostAnalysisSeries(
        slots=slots,
        consumer_labels=_consumer_labels(flex),
        data_start=slots[0].slot_start,
        data_end=slots[-1].slot_start,
    )


def filter_slots_iso_week(
    slots: Sequence[CostAnalysisSlot],
    *,
    iso_year: int,
    iso_week: int,
) -> tuple[CostAnalysisSlot, ...]:
    return tuple(
        slot
        for slot in slots
        if slot.slot_start.isocalendar()[:2] == (iso_year, iso_week)
    )


def filter_slots_calendar_month(
    slots: Sequence[CostAnalysisSlot],
    *,
    year: int,
    month: int,
) -> tuple[CostAnalysisSlot, ...]:
    return tuple(
        slot
        for slot in slots
        if slot.slot_start.year == year and slot.slot_start.month == month
    )


def filter_slots_calendar_year(
    slots: Sequence[CostAnalysisSlot],
    *,
    year: int,
) -> tuple[CostAnalysisSlot, ...]:
    return tuple(slot for slot in slots if slot.slot_start.year == year)


def iso_weeks_in_slots(slots: Sequence[CostAnalysisSlot]) -> list[tuple[int, int]]:
    weeks: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for slot in slots:
        key = slot.slot_start.isocalendar()[:2]
        if key in seen:
            continue
        seen.add(key)
        weeks.append(key)
    return weeks


def aggregate_slots(slots: Sequence[CostAnalysisSlot]) -> PeriodTotals:
    """Sum energy and costs over slots (rough trust totals)."""
    by_id: dict[str, list[float]] = {}
    energy = pv = batt = grid = cost = 0.0
    charge = discharge = charge_pv = charge_grid = 0.0
    discharge_load = export_batt = 0.0
    for slot in slots:
        charge += slot.battery_charge_kwh
        discharge += slot.battery_discharge_kwh
        charge_pv += slot.charge_from_pv_kwh
        charge_grid += slot.charge_from_grid_kwh
        discharge_load += slot.discharge_to_load_kwh
        export_batt += slot.export_from_battery_kwh
        for share in slot.shares:
            bucket = by_id.setdefault(share.consumer_id, [0.0, 0.0, 0.0, 0.0])
            bucket[0] += share.pv_kwh
            bucket[1] += share.battery_kwh
            bucket[2] += share.grid_kwh
            bucket[3] += share.cost_euro
            energy += share.pv_kwh + share.battery_kwh + share.grid_kwh
            pv += share.pv_kwh
            batt += share.battery_kwh
            grid += share.grid_kwh
            cost += share.cost_euro

    consumer_totals = {
        cid: ConsumerSlotShare(
            consumer_id=cid,
            load_kw=0.0,
            pv_kwh=round(values[0], 4),
            battery_kwh=round(values[1], 4),
            grid_kwh=round(values[2], 4),
            cost_euro=round(values[3], 4),
        )
        for cid, values in by_id.items()
    }
    return PeriodTotals(
        energy_kwh=round(energy, 4),
        pv_kwh=round(pv, 4),
        battery_kwh=round(batt, 4),
        grid_kwh=round(grid, 4),
        cost_euro=round(cost, 4),
        by_consumer=consumer_totals,
        battery_charge_kwh=round(charge, 4),
        battery_discharge_kwh=round(discharge, 4),
        charge_from_pv_kwh=round(charge_pv, 4),
        charge_from_grid_kwh=round(charge_grid, 4),
        discharge_to_load_kwh=round(discharge_load, 4),
        export_from_battery_kwh=round(export_batt, 4),
        slot_count=len(slots),
    )
