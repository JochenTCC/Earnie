"""
history_timeline.py – 24h-Historie aus optimization_history.jsonl (96 Viertelstunden-Slots).

Rekonstruiert das tatsächliche Produktiv-Verhalten; fehlende Slots per Hold-Forward.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import config
from optimizer import battery as bat
from optimizer.consumer_power import uses_pv_follow
from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start
from optimizer.simulation import calculate_step_cost_euro_from_row, flexible_consumer_power_kw
from optimizer.targets import consumer_column_name, consumer_pv_follow_column_name

from . import optimization_history

SLOTS_PER_DAY = 96
SLOT_DURATION_HOURS = QUARTER_HOUR_MINUTES / 60.0


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


def _format_slot_time(slot_start: datetime) -> str:
    return slot_start.strftime("%H:%M")


def _parse_completed_at(entry: dict[str, Any]) -> datetime | None:
    text = entry.get("completed_at")
    if isinstance(text, datetime):
        return text
    if text:
        try:
            return datetime.fromisoformat(str(text))
        except ValueError:
            pass
    written = entry.get("written_at")
    if not written:
        return None
    try:
        return datetime.fromisoformat(str(written))
    except ValueError:
        return None


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


def _consumer_kw_from_entry(
    entry: dict[str, Any],
    consumer_id: str,
) -> float:
    powers = entry.get("consumer_powers_kw") or {}
    if consumer_id in powers:
        return float(powers[consumer_id] or 0.0)
    snapshot = entry.get("consumption_snapshot") or {}
    flex_kw = snapshot.get("flex_kw") or {}
    return float(flex_kw.get(consumer_id, 0.0) or 0.0)


def entry_to_chart_row(entry: dict[str, Any], slot_start: datetime) -> dict[str, Any]:
    """Baut eine Chart-Zeile aus einem Produktiv-Durchlauf."""
    mode = int(entry.get("mode", bat.MODE_AUTOMATIK))
    target_power = float(entry.get("target_power_kw", 0.0) or 0.0)
    pv, baseload, battery_plan = _power_kw_from_entry(entry)
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start),
        "Strompreis (Cent/kWh)": round(float(entry.get("market_price_cent", 0.0) or 0.0), 4),
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": round(pv, 3),
        "Verbrauch-Prognose (kW)": round(baseload, 3),
        "Geplante Batterie-Aktion (kW)": round(battery_plan, 3),
        "Simulierter SoC (%)": round(float(entry.get("soc_percent", 0.0) or 0.0), 1),
        "Steuerbefehl": bat.steuerbefehl_for_mode(mode, target_power),
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        row[consumer_column_name(consumer)] = round(_consumer_kw_from_entry(entry, cid), 2)
        if uses_pv_follow(consumer):
            pv_follow = (entry.get("consumer_pv_follow") or {}).get(cid, 0)
            row[consumer_pv_follow_column_name(consumer)] = int(pv_follow or 0)
    row["Netzbezug (kW)"] = round(
        baseload + flexible_consumer_power_kw(row) - pv + battery_plan,
        2,
    )
    return row


def _hold_forward_row(previous: dict[str, Any], slot_start: datetime) -> dict[str, Any]:
    row = dict(previous)
    row["slot_datetime"] = slot_start
    row["Uhrzeit"] = _format_slot_time(slot_start)
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
            candidate = by_slot.get(slot)
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


def build_history_timeline(
    offset_days: int,
    now: datetime | None = None,
) -> HistoryTimelineResult:
    """
    Rekonstruiert 96 Viertelstunden-Slots für ein vergangenes 24h-Fenster.

    Fehlende Slots: Hold-Forward des letzten bekannten Werts (Preis/SoC/Leistung).
    """
    window_start, window_end, anchor = history_window_bounds(offset_days, now)
    entries = optimization_history.load_replay_entries_between(window_start, window_end)
    by_slot = _index_entries_by_slot(entries)
    sell_price_cent = config.get_push_price_cent()

    rows: list[dict[str, Any]] = []
    present = held = missing = 0
    last_row: dict[str, Any] | None = None

    for slot_start in _slot_starts(window_start):
        entry = by_slot.get(slot_start)
        if entry is not None:
            row = entry_to_chart_row(entry, slot_start)
            present += 1
            last_row = row
        elif last_row is not None:
            row = _hold_forward_row(last_row, slot_start)
            held += 1
        else:
            row = _empty_chart_row(slot_start)
            missing += 1
        rows.append(row)

    slot_costs = [_slot_cost_euro(row, sell_price_cent) for row in rows]
    slot_kwh = [_slot_consumption_kwh(row) for row in rows]
    slot_starts = _slot_starts(window_start)
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
        window_start=window_start,
        window_end=window_end,
        anchor_slot=anchor,
        offset_days=offset_days,
    )


def _empty_chart_row(slot_start: datetime) -> dict[str, Any]:
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start),
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
