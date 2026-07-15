"""
history_timeline.py – 24h-Historie aus optimization_history.jsonl (96 Viertelstunden-Slots).

Rekonstruiert das tatsächliche Produktiv-Verhalten. S-2-Charts (`build_chart_history`): fehlende Slots leer.
96h-Archiv (`build_history_timeline`): Hold-Forward für SoC/Preis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import config
from data.planning_window import align_to_planning_timezone
from optimizer import battery as bat
from optimizer.consumer_power import uses_pv_follow
from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start
from optimizer.simulation import calculate_step_cost_euro_from_row, flexible_consumer_power_kw
from optimizer.targets import (
    consumer_column_name,
    consumer_immediate_charge_column_name,
    consumer_pv_follow_column_name,
)
from settings.flexible_consumers import charging_context_lookup

from . import optimization_history

SLOTS_PER_DAY = 96
SLOT_DURATION_HOURS = QUARTER_HOUR_MINUTES / 60.0

SLOT_PRESENT = "present"

# Chart-1-Rauf/Runter: gemessene Batterieleistung (kW, positiv = laden) aus Loxone-Snapshot
CHART_IST_BATTERY_KW_COLUMN = "Ist Batterie-Leistung (kW)"
PV_IST_COLUMN = "PV-Ist (kW)"
SLOT_HELD = "held"
SLOT_MISSING = "missing"


@dataclass(frozen=True)
class ChartHistoryResult:
    """15-Min-Slots aus dem Produktiv-Log für ein beliebiges Chart-Fenster."""

    rows: list[dict[str, Any]]
    slot_starts: tuple[datetime, ...]
    slot_qualities: tuple[str, ...]
    slot_costs_euro: list[float]
    cumulative_costs_euro: list[float]
    slot_consumption_kwh: list[float]
    cumulative_consumption_kwh: list[float]
    present_slot_count: int
    held_slot_count: int
    missing_slot_count: int
    window_start: datetime
    window_end_exclusive: datetime
    slot_deviation_events: tuple[tuple[Any, ...], ...] = ()


@dataclass(frozen=True)
class HistoryTimelineResult:
    """96 Viertelstunden-Slots eines vergangenen 24h-Fensters."""

    rows: list[dict[str, Any]]
    slot_costs_euro: list[float]
    cumulative_costs_euro: list[float]
    slot_consumption_kwh: list[float]
    cumulative_consumption_kwh: list[float]
    projected_savings_cumulative_euro: list[float]
    projected_savings_available: bool
    latest_projected_savings_euro: float | None
    present_slot_count: int
    held_slot_count: int
    missing_slot_count: int
    slot_qualities: tuple[str, ...]
    window_start: datetime
    window_end: datetime
    anchor_slot: datetime
    offset_days: int


def live_anchor_slot(now: datetime | None = None) -> datetime:
    """Anker wie im Live-Modus: Beginn des aktuellen Viertelstunden-Slots."""
    return quarter_hour_slot_start(now)


def history_window_bounds(
    offset_days: int,
    now: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    """
    Grenzen für einen Historie-Schritt.

    offset_days=1 → [Anker−24h, Anker); Anker = aktueller Live-Slot-Start.
    """
    if offset_days < 1:
        raise ValueError(
            f"offset_days muss >= 1 sein (0 = Live-Modus), erhalten: {offset_days}"
        )
    anchor = live_anchor_slot(now)
    window_end = anchor - timedelta(days=offset_days - 1)
    window_start = window_end - timedelta(days=1)
    return window_start, window_end, anchor


def max_history_offset_days(now: datetime | None = None) -> int:
    """Maximale Anzahl 24h-Schritte zurück (solange Fensterstart >= frühestem Eintrag)."""
    earliest = optimization_history.earliest_replay_completed_at()
    if earliest is None:
        return 0
    anchor = live_anchor_slot(now)
    earliest_slot = quarter_hour_slot_start(earliest)
    offset = 0
    while True:
        next_offset = offset + 1
        window_start, _, _ = history_window_bounds(next_offset, now)
        if window_start < earliest_slot:
            break
        offset = next_offset
    return offset


def _slot_starts(window_start: datetime) -> list[datetime]:
    step = timedelta(minutes=QUARTER_HOUR_MINUTES)
    return [window_start + step * index for index in range(SLOTS_PER_DAY)]


def _format_slot_time(slot_start: datetime, *, include_date: bool = False) -> str:
    if include_date:
        return slot_start.strftime("%d.%m. %H:%M")
    return slot_start.strftime("%H:%M")


def _align_log_timestamp(moment: datetime) -> datetime:
    return align_to_planning_timezone(moment, config.get_planning_timezone())


def _parse_completed_at(entry: dict[str, Any]) -> datetime | None:
    text = entry.get("completed_at")
    parsed: datetime | None
    if isinstance(text, datetime):
        parsed = text
    elif text:
        try:
            parsed = datetime.fromisoformat(str(text))
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None:
        written = entry.get("written_at")
        if not written:
            return None
        try:
            parsed = datetime.fromisoformat(str(written))
        except ValueError:
            return None
    return _align_log_timestamp(parsed)


def quarter_hour_slots_between(
    window_start: datetime,
    window_end_exclusive: datetime,
) -> tuple[datetime, ...]:
    """Viertelstunden-Slots in [window_start, window_end_exclusive)."""
    if window_start.tzinfo is None or window_end_exclusive.tzinfo is None:
        raise ValueError("window_start und window_end_exclusive müssen timezone-aware sein.")
    if window_end_exclusive <= window_start:
        return ()
    step = timedelta(minutes=QUARTER_HOUR_MINUTES)
    slot = _coerce_slot_start(window_start)
    end_bound = _coerce_slot_start(window_end_exclusive)
    if window_end_exclusive > end_bound:
        end_bound += step
    slots: list[datetime] = []
    while slot < end_bound and slot < window_end_exclusive:
        slots.append(slot)
        slot += step
    return tuple(slots)


def _coerce_slot_start(slot_start: datetime) -> datetime:
    """Slot-Schlüssel für Log-Lookup (aware, Planungs-TZ)."""
    if slot_start.tzinfo is None:
        return quarter_hour_slot_start(_align_log_timestamp(slot_start))
    return quarter_hour_slot_start(slot_start)


def _index_entries_by_slot(
    entries: list[dict[str, Any]],
) -> dict[datetime, dict[str, Any]]:
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


def _pv_forecast_kw_from_entry(entry: dict[str, Any]) -> float:
    return float(entry.get("forecast_pv_kw", 0.0) or 0.0)


def _power_kw_from_entry(entry: dict[str, Any]) -> tuple[float, float, float]:
    snapshot = entry.get("consumption_snapshot") or {}
    pv = snapshot.get("pv_kw")
    if pv is None:
        pv = entry.get("forecast_pv_kw", 0.0)
    baseload = snapshot.get("baseload_kw")
    if baseload is None:
        baseload = entry.get("forecast_consumption_kw", 0.0)
    battery_plan = entry.get("battery_plan_kw")
    if battery_plan is None:
        mode = int(entry.get("mode", bat.MODE_AUTOMATIK))
        target_power = float(entry.get("target_power_kw", 0.0) or 0.0)
        if mode in (bat.MODE_ZWANGS_LADEN, bat.MODE_ZWANGS_ENTLADEN):
            battery_plan = target_power if mode == bat.MODE_ZWANGS_LADEN else -target_power
        else:
            battery_plan = 0.0
    return float(pv), float(baseload), float(battery_plan)


def _chart_battery_kw_from_snapshot(snapshot: dict[str, Any]) -> float | None:
    """Loxone ``battery_kw`` (negativ = laden) → Chart-Vorzeichen (positiv = laden)."""
    raw = snapshot.get("battery_kw")
    if raw is None:
        return None
    return round(-float(raw), 3)


def _pv_kw_for_balance(row: dict[str, Any]) -> float:
    """PV für Energiebilanz: Ist aus Log-Snapshot, sonst Prognose."""
    if PV_IST_COLUMN in row:
        raw = row.get(PV_IST_COLUMN)
        if raw is not None:
            try:
                ist = float(raw)
                if not math.isnan(ist):
                    return ist
            except (TypeError, ValueError):
                pass
    return float(row.get("PV-Prognose (kW)", 0.0) or 0.0)


def _netzbezug_kw_from_entry(entry: dict[str, Any], row: dict[str, Any]) -> float:
    """Netzbezug: gemessenes grid_kw aus consumption_snapshot, sonst Bilanz aus der Zeile."""
    snapshot = entry.get("consumption_snapshot") or {}
    grid = snapshot.get("grid_kw")
    if grid is not None:
        return round(float(grid), 2)
    return round(
        float(row["Verbrauch-Prognose (kW)"])
        + flexible_consumer_power_kw(row)
        - _pv_kw_for_balance(row)
        + float(row["Geplante Batterie-Aktion (kW)"]),
        2,
    )


def _consumer_kw_from_entry(
    entry: dict[str, Any],
    consumer_id: str,
) -> float | None:
    """Flex-Leistung für Chart/Tabelle im Produktiv-Log — Ist, nicht MILP-Soll."""
    measured_ids = entry.get("flex_measured_ids")
    if measured_ids is not None and consumer_id not in measured_ids:
        return None

    snapshot = entry.get("consumption_snapshot") or {}
    flex_kw = snapshot.get("flex_kw") or {}
    if consumer_id in flex_kw:
        return float(flex_kw[consumer_id] or 0.0)
    live = entry.get("flex_live_kw") or {}
    if consumer_id in live:
        return float(live[consumer_id] or 0.0)
    if measured_ids is not None:
        return None
    return 0.0


def _immediate_charge_flags_from_entry(entry: dict[str, Any] | None) -> dict[str, int]:
    """Sofort-Laden-Flags aus dem gespeicherten charging_contexts (falls vorhanden)."""
    contexts = (entry or {}).get("charging_contexts") or {}
    flags: dict[str, int] = {}
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        ctx = charging_context_lookup(contexts, consumer)
        flags[consumer_immediate_charge_column_name(consumer)] = (
            1 if ctx.get("immediate_charge") else 0
        )
    return flags


def _feed_in_price_cent_from_entry(entry: dict[str, Any] | None) -> float:
    """Einspeisevergütung aus k_push_act im Log, sonst fixer Config-Fallback."""
    if entry is not None and entry.get("k_push_act") is not None:
        return round(float(entry["k_push_act"]), 4)
    return round(config.get_push_price_cent(), 4)


def _append_milp_table_columns(row: dict[str, Any], entry: dict[str, Any] | None) -> None:
    """
    Spalten, die nur in MILP-Chart-Zeilen vorkommen — für die Tabelle mit Defaults befüllen.

    Einspeisevergütung: k_push_act aus dem Produktiv-Lauf, sonst Config-Fallback.
    sofort_laden: aus charging_contexts des Produktiv-Laufs, sonst 0.
    """
    row["Einspeisevergütung (Cent/kWh)"] = _feed_in_price_cent_from_entry(entry)
    row.update(_immediate_charge_flags_from_entry(entry))


def entry_to_chart_row(
    entry: dict[str, Any],
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    """Baut eine Chart-Zeile aus einem Produktiv-Durchlauf."""
    mode = int(entry.get("mode", bat.MODE_AUTOMATIK))
    target_power = float(entry.get("target_power_kw", 0.0) or 0.0)
    _, baseload, battery_plan = _power_kw_from_entry(entry)
    snapshot = entry.get("consumption_snapshot") or {}
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start, include_date=include_date),
        "Strompreis (Cent/kWh)": round(float(entry.get("market_price_cent", 0.0) or 0.0), 4),
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": round(_pv_forecast_kw_from_entry(entry), 3),
        "Verbrauch-Prognose (kW)": round(baseload, 3),
        "Geplante Batterie-Aktion (kW)": round(battery_plan, 3),
        "Simulierter SoC (%)": round(float(entry.get("soc_percent", 0.0) or 0.0), 1),
        "Steuerbefehl": bat.steuerbefehl_for_mode(mode, target_power),
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        flex_kw = _consumer_kw_from_entry(entry, cid)
        row[consumer_column_name(consumer)] = (
            round(flex_kw, 2) if flex_kw is not None else None
        )
        if uses_pv_follow(consumer):
            pv_follow = (entry.get("consumer_pv_follow") or {}).get(cid, 0)
            row[consumer_pv_follow_column_name(consumer)] = int(pv_follow or 0)
    if snapshot.get("pv_kw") is not None:
        row[PV_IST_COLUMN] = round(float(snapshot["pv_kw"]), 3)
    row["Netzbezug (kW)"] = _netzbezug_kw_from_entry(entry, row)
    ist_battery = _chart_battery_kw_from_snapshot(snapshot)
    if ist_battery is not None:
        row[CHART_IST_BATTERY_KW_COLUMN] = ist_battery
    _append_milp_table_columns(row, entry)
    return row


def _zero_flex_power(row: dict[str, Any]) -> None:
    """Hold-Forward gilt für SoC/Preis — flexible Verbraucher bleiben aus."""
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        row[consumer_column_name(consumer)] = 0.0
        if uses_pv_follow(consumer):
            row[consumer_pv_follow_column_name(consumer)] = 0
    baseload = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
    battery_plan = float(row.get("Geplante Batterie-Aktion (kW)", 0.0) or 0.0)
    row["Netzbezug (kW)"] = round(
        baseload - _pv_kw_for_balance(row) + battery_plan,
        2,
    )


def _hold_forward_row(
    previous: dict[str, Any],
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    row = dict(previous)
    row["slot_datetime"] = slot_start
    row["Uhrzeit"] = _format_slot_time(slot_start, include_date=include_date)
    row.pop(CHART_IST_BATTERY_KW_COLUMN, None)
    row.pop(PV_IST_COLUMN, None)
    _zero_flex_power(row)
    return row


def _slot_cost_euro(row: dict[str, Any], sell_price_cent: float) -> float:
    hourly = calculate_step_cost_euro_from_row(row, sell_price_cent)
    return round(hourly * SLOT_DURATION_HOURS, 6)


def _slot_consumption_kwh(row: dict[str, Any]) -> float:
    power = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0) + flexible_consumer_power_kw(row)
    return round(power * SLOT_DURATION_HOURS, 6)


def _cumulative(values: list[float]) -> list[float]:
    total = 0.0
    result: list[float] = []
    for value in values:
        total += value
        result.append(round(total, 4))
    return result


def _entry_savings_snapshot(entry: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = entry.get("savings_snapshot")
    if not isinstance(snapshot, dict):
        return None
    if not snapshot.get("hourly_savings_euro"):
        return None
    return snapshot


def _projected_hourly_savings_from_slots(
    by_slot: dict[datetime, dict[str, Any]],
    slot_starts: list[datetime],
) -> list[float]:
    """
    Pro Clock-Stunde: Stunden-Ersparnis aus dem letzten Lauf dieser Stunde.

    Verwendet hourly_savings_euro[0] (Ersparnis für die laufende Stunde).
    Fehlende Stunden werden mit 0.0 befüllt.
    """
    hours = len(slot_starts) // 4
    hourly: list[float] = []
    step = timedelta(minutes=QUARTER_HOUR_MINUTES)
    for hour in range(hours):
        hour_start = slot_starts[hour * 4]
        entry = None
        for quarter in range(4):
            slot = hour_start + step * quarter
            candidate = by_slot.get(_coerce_slot_start(slot))
            if candidate is not None and _entry_savings_snapshot(candidate) is not None:
                entry = candidate
        if entry is None:
            hourly.append(0.0)
            continue
        snapshot = _entry_savings_snapshot(entry)
        assert snapshot is not None
        values = snapshot.get("hourly_savings_euro") or []
        hourly.append(float(values[0]) if values else 0.0)
    return hourly


def _hourly_to_slot_cumulative(hourly: list[float], slot_count: int) -> list[float]:
    """Kumulierte Stunden-Ersparnis auf Viertelstunden-Slots (HV-Linie)."""
    if not hourly:
        return [0.0] * slot_count
    hourly_cum: list[float] = []
    total = 0.0
    for value in hourly:
        total += float(value)
        hourly_cum.append(round(total, 4))
    slot_values: list[float] = []
    for hour_total in hourly_cum:
        slot_values.extend([hour_total] * 4)
    if len(slot_values) < slot_count:
        slot_values.extend([slot_values[-1] if slot_values else 0.0] * (slot_count - len(slot_values)))
    return slot_values[:slot_count]


def _latest_projected_savings_euro(
    by_slot: dict[datetime, dict[str, Any]],
) -> float | None:
    latest_at: datetime | None = None
    latest_value: float | None = None
    for completed, entry in (
        (_parse_completed_at(entry), entry)
        for entry in by_slot.values()
    ):
        if completed is None:
            continue
        snapshot = _entry_savings_snapshot(entry)
        if snapshot is None:
            continue
        if latest_at is None or completed > latest_at:
            latest_at = completed
            latest_value = float(snapshot.get("savings_matched_euro", 0.0))
    return latest_value


def _projected_savings_available(by_slot: dict[datetime, dict[str, Any]]) -> bool:
    return any(_entry_savings_snapshot(entry) is not None for entry in by_slot.values())


def _build_rows_for_slot_starts(
    slot_starts: tuple[datetime, ...] | list[datetime],
    *,
    include_date: bool = False,
    hold_forward: bool = True,
) -> tuple[list[dict[str, Any]], tuple[str, ...], int, int, int, dict[datetime, dict[str, Any]]]:
    if not slot_starts:
        return [], (), 0, 0, 0, {}
    starts = tuple(slot_starts)
    window_start = _coerce_slot_start(starts[0])
    window_end = _coerce_slot_start(starts[-1]) + timedelta(minutes=QUARTER_HOUR_MINUTES)
    entries = optimization_history.load_replay_entries_between(window_start, window_end)
    by_slot = _index_entries_by_slot(entries)
    rows: list[dict[str, Any]] = []
    qualities: list[str] = []
    present = held = missing = 0
    last_row: dict[str, Any] | None = None
    for slot_start in starts:
        slot_key = _coerce_slot_start(slot_start)
        entry = by_slot.get(slot_key)
        if entry is not None:
            row = entry_to_chart_row(entry, slot_key, include_date=include_date)
            present += 1
            last_row = row
            qualities.append(SLOT_PRESENT)
        elif hold_forward and last_row is not None:
            row = _hold_forward_row(last_row, slot_key, include_date=include_date)
            held += 1
            qualities.append(SLOT_HELD)
        elif hold_forward:
            row = _empty_chart_row(slot_key, include_date=include_date)
            missing += 1
            qualities.append(SLOT_MISSING)
        else:
            row = _missing_chart_row(slot_key, include_date=include_date)
            missing += 1
            qualities.append(SLOT_MISSING)
        rows.append(row)
    return rows, tuple(qualities), present, held, missing, by_slot


def build_chart_history(
    window_start: datetime,
    window_end_exclusive: datetime,
) -> ChartHistoryResult:
    """
    Rekonstruiert 15-Min-Ist-Daten für [window_start, window_end_exclusive).

    Fensterende exklusiv = history_boundary_exclusive(now) (Spec ui-sunset2sunset v0.6 §6).
    """
    if window_start.tzinfo is None or window_end_exclusive.tzinfo is None:
        raise ValueError("window_start und window_end_exclusive müssen timezone-aware sein.")
    if window_end_exclusive <= window_start:
        return ChartHistoryResult(
            rows=[],
            slot_starts=(),
            slot_qualities=(),
            slot_costs_euro=[],
            cumulative_costs_euro=[],
            slot_consumption_kwh=[],
            cumulative_consumption_kwh=[],
            present_slot_count=0,
            held_slot_count=0,
            missing_slot_count=0,
            window_start=window_start,
            window_end_exclusive=window_end_exclusive,
            slot_deviation_events=(),
        )
    slot_starts = quarter_hour_slots_between(window_start, window_end_exclusive)
    rows, qualities, present, held, missing, by_slot = _build_rows_for_slot_starts(
        slot_starts,
        include_date=True,
        hold_forward=False,
    )
    from optimizer.deviation_timeline import build_slot_deviation_series

    deviation_events = build_slot_deviation_series(by_slot, slot_starts, qualities)
    sell_price_cent = config.get_push_price_cent()
    slot_costs = [
        0.0 if quality == SLOT_MISSING else _slot_cost_euro(row, sell_price_cent)
        for row, quality in zip(rows, qualities)
    ]
    slot_kwh = [
        0.0 if quality == SLOT_MISSING else _slot_consumption_kwh(row)
        for row, quality in zip(rows, qualities)
    ]
    return ChartHistoryResult(
        rows=rows,
        slot_starts=slot_starts,
        slot_qualities=qualities,
        slot_costs_euro=slot_costs,
        cumulative_costs_euro=_cumulative(slot_costs),
        slot_consumption_kwh=slot_kwh,
        cumulative_consumption_kwh=_cumulative(slot_kwh),
        present_slot_count=present,
        held_slot_count=held,
        missing_slot_count=missing,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        slot_deviation_events=deviation_events,
    )


def build_history_timeline(
    offset_days: int,
    now: datetime | None = None,
) -> HistoryTimelineResult:
    """
    Rekonstruiert 96 Viertelstunden-Slots für ein vergangenes 24h-Fenster.

    Fehlende Slots: Hold-Forward des letzten bekannten Werts (Preis/SoC; Flex = 0 kW).
    """
    window_start, window_end, anchor = history_window_bounds(offset_days, now)
    slot_starts = _slot_starts(window_start)
    rows, qualities, present, held, missing, _by_slot = _build_rows_for_slot_starts(slot_starts)
    entries = optimization_history.load_replay_entries_between(window_start, window_end)
    by_slot = _index_entries_by_slot(entries)
    sell_price_cent = config.get_push_price_cent()

    slot_costs = [_slot_cost_euro(row, sell_price_cent) for row in rows]
    slot_kwh = [_slot_consumption_kwh(row) for row in rows]
    projected_hourly = _projected_hourly_savings_from_slots(by_slot, slot_starts)
    projected_savings_cum = _hourly_to_slot_cumulative(projected_hourly, len(slot_starts))
    savings_available = _projected_savings_available(by_slot)

    return HistoryTimelineResult(
        rows=rows,
        slot_costs_euro=slot_costs,
        cumulative_costs_euro=_cumulative(slot_costs),
        slot_consumption_kwh=slot_kwh,
        cumulative_consumption_kwh=_cumulative(slot_kwh),
        projected_savings_cumulative_euro=projected_savings_cum,
        projected_savings_available=savings_available,
        latest_projected_savings_euro=_latest_projected_savings_euro(by_slot),
        present_slot_count=present,
        held_slot_count=held,
        missing_slot_count=missing,
        slot_qualities=qualities,
        window_start=window_start,
        window_end=window_end,
        anchor_slot=anchor,
        offset_days=offset_days,
    )


def _missing_chart_row(
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    """Leere Zeile für fehlende Log-Slots (S-2, Spec v0.6.1 — kein Hold-Forward)."""
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start, include_date=include_date),
        "Strompreis (Cent/kWh)": None,
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": None,
        PV_IST_COLUMN: None,
        "Verbrauch-Prognose (kW)": None,
        "Geplante Batterie-Aktion (kW)": None,
        "Netzbezug (kW)": None,
        "Simulierter SoC (%)": None,
        "Steuerbefehl": "",
        "Einspeisevergütung (Cent/kWh)": None,
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        row[consumer_column_name(consumer)] = None
        if uses_pv_follow(consumer):
            row[consumer_pv_follow_column_name(consumer)] = None
        row[consumer_immediate_charge_column_name(consumer)] = None
    return row


def _empty_chart_row(
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start, include_date=include_date),
        "Strompreis (Cent/kWh)": 0.0,
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": 0.0,
        "Verbrauch-Prognose (kW)": 0.0,
        "Geplante Batterie-Aktion (kW)": 0.0,
        "Netzbezug (kW)": 0.0,
        "Simulierter SoC (%)": 0.0,
        "Steuerbefehl": bat.steuerbefehl_for_mode(bat.MODE_AUTOMATIK, 0.0),
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        row[consumer_column_name(consumer)] = 0.0
        if uses_pv_follow(consumer):
            row[consumer_pv_follow_column_name(consumer)] = 0
    _append_milp_table_columns(row, None)
    return row


def format_gap_notice(result: HistoryTimelineResult) -> str | None:
    """Hinweistext für fehlende oder gehaltene Slots (Spezifikation B+C)."""
    parts: list[str] = []
    if result.missing_slot_count:
        parts.append(f"{result.missing_slot_count} von {SLOTS_PER_DAY} Slots ohne Daten")
    if result.held_slot_count:
        parts.append(f"{result.held_slot_count} Slots mit letztem bekannten Wert aufgefüllt")
    if not parts:
        return None
    return " · ".join(parts)
