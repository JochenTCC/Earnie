"""Live-Chart: S-2-Segmente SA₀→SA₁ / SA₁→SA₂, Zonen und Kosten-Summen."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config
from data.planning_window import (
    PlanningWindow,
    UiChartWindow,
    UiChartZones,
    compute_ui_chart_window,
    history_log_end_exclusive,
    normalize_hour_slot,
    normalize_planning_hour_slot,
    ui_chart_zones,
)
from runtime_store import optimization_history
from optimizer.deviation_eval import DeviationEvent
from optimizer.deviation_timeline import empty_deviation_series
from runtime_store.history_timeline import (
    ChartHistoryResult,
    SLOT_MISSING,
    SLOT_PRESENT,
    build_chart_history,
    quarter_hour_slots_between,
)

SLOT_MILP = "milp"


@dataclass(frozen=True)
class ChartDisplayContext:
    """Gemischte Chart-/Tabellen-Zeilen: Produktiv-Log (15 min) + MILP (1 h)."""

    rows: list[dict]
    slot_datetimes: tuple[datetime, ...]
    slot_qualities: tuple[str, ...]
    history_slot_count: int
    history_result: ChartHistoryResult | None
    gap_notice: str | None
    history_only: bool
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] = ()


@dataclass(frozen=True)
class LiveChartContext:
    """Darstellungskontext für den Live-Optimierungschart."""

    now: datetime
    chart_window: UiChartWindow
    zones: UiChartZones
    cycle_offset: int
    segment_index: int
    zone_reference: datetime
    planning_window: PlanningWindow | None = None


def live_now() -> datetime:
    tz = ZoneInfo(config.get_planning_timezone())
    return datetime.now(tz).replace(second=0, microsecond=0)


def max_sunrise_cycle_offset(now: datetime | None = None) -> int:
    """Max. SA-Zyklen zurück, solange SA₀ >= frühestem JSONL-Eintrag."""
    earliest = optimization_history.earliest_replay_completed_at()
    if earliest is None:
        return 0
    moment = now if now is not None else live_now()
    if moment.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    lat = config.get("LATITUDE", cast=float)
    lon = config.get("LONGITUDE", cast=float)
    tz_name = config.get_planning_timezone()
    earliest_slot = normalize_planning_hour_slot(earliest, tz_name)
    offset = 0
    while True:
        next_offset = offset + 1
        chart = compute_ui_chart_window(
            moment, lat, lon, tz_name, cycle_offset=next_offset
        )
        if normalize_hour_slot(chart.sa0) < earliest_slot:
            break
        offset = next_offset
    return offset


def s2_navigable_cycles(now: datetime | None = None) -> list[tuple[int, datetime]]:
    """(cycle_offset, SA₀) für jeden navigierbaren Zyklus (0 = Live)."""
    moment = now if now is not None else live_now()
    if moment.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    lat = config.get("LATITUDE", cast=float)
    lon = config.get("LONGITUDE", cast=float)
    tz_name = config.get_planning_timezone()
    max_cycle = max_sunrise_cycle_offset(moment)
    return [
        (
            offset,
            compute_ui_chart_window(
                moment, lat, lon, tz_name, cycle_offset=offset
            ).sa0,
        )
        for offset in range(max_cycle + 1)
    ]


def sa0_date_for_s2_cycle(cycle_offset: int, now: datetime | None = None) -> date:
    """Kalenderdatum von SA₀ für einen Zyklus-Offset."""
    if cycle_offset < 0:
        raise ValueError(f"cycle_offset muss >= 0 sein, erhalten: {cycle_offset}.")
    moment = now if now is not None else live_now()
    if moment.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    lat = config.get("LATITUDE", cast=float)
    lon = config.get("LONGITUDE", cast=float)
    tz_name = config.get_planning_timezone()
    chart = compute_ui_chart_window(
        moment, lat, lon, tz_name, cycle_offset=cycle_offset
    )
    return chart.sa0.date()


def cycle_offset_for_sa0_date(target: date, now: datetime | None = None) -> int | None:
    """Zyklus-Offset zu einem SA₀-Kalenderdatum; None wenn nicht navigierbar."""
    for offset, sa0 in s2_navigable_cycles(now):
        if sa0.date() == target:
            return offset
    return None


def s2_date_picker_bounds(now: datetime | None = None) -> tuple[date, date] | None:
    """Min-/Max-Datum für die S-2-Datumsauswahl (nur Tage mit Log-Daten)."""
    cycles = s2_navigable_cycles(now)
    if not cycles:
        return None
    dates = [sa0.date() for _, sa0 in cycles]
    return min(dates), max(dates)


def build_live_chart_context(
    cycle_offset: int,
    segment_index: int,
    *,
    now: datetime | None = None,
    planning_window: PlanningWindow | None = None,
    sim_rows: list[dict] | None = None,
) -> LiveChartContext:
    if cycle_offset < 0:
        raise ValueError(f"cycle_offset muss >= 0 sein, erhalten: {cycle_offset}.")
    if segment_index not in (0, 1):
        raise ValueError(
            f"segment_index muss 0 oder 1 sein, erhalten: {segment_index}."
        )
    moment = now if now is not None else live_now()
    if moment.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    lat = config.get("LATITUDE", cast=float)
    lon = config.get("LONGITUDE", cast=float)
    tz_name = config.get_planning_timezone()
    chart = compute_ui_chart_window(
        moment,
        lat,
        lon,
        tz_name,
        segment_index=segment_index,
        cycle_offset=cycle_offset,
    )
    is_live_segment = cycle_offset == 0 and segment_index == 0
    reference = moment if is_live_segment else chart.end
    zone_now = moment if is_live_segment else chart.end
    zones = ui_chart_zones(
        zone_now,
        chart,
        sim_rows=sim_rows,
        is_live_segment=is_live_segment,
    )
    return LiveChartContext(
        now=moment,
        chart_window=chart,
        zones=zones,
        cycle_offset=cycle_offset,
        segment_index=segment_index,
        zone_reference=reference,
        planning_window=planning_window,
    )


def _row_slot(row: dict) -> datetime | None:
    slot = row.get("slot_datetime")
    if slot is None:
        return None
    if isinstance(slot, datetime):
        return normalize_hour_slot(slot)
    return None


def matrix_indices_for_chart(
    matrix: list[dict],
    chart: UiChartWindow,
) -> list[int]:
    indices: list[int] = []
    for index, row in enumerate(matrix):
        slot = _row_slot(row)
        if slot is None:
            continue
        if chart.start <= slot <= chart.end:
            indices.append(index)
    return indices


def _empty_chart_row(slot: datetime) -> dict:
    return {
        "slot_datetime": slot,
        "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
        "Strompreis (Cent/kWh)": None,
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": 0.0,
        "Verbrauch-Prognose (kW)": 0.0,
        "Geplante Batterie-Aktion (kW)": 0.0,
        "Netzbezug (kW)": 0.0,
        "Simulierter SoC (%)": None,
        "Steuerbefehl": "",
    }


def align_rows_to_chart_slots(
    sim_rows: list[dict],
    chart: UiChartWindow,
) -> list[dict]:
    by_slot: dict[datetime, dict] = {}
    for row in sim_rows:
        slot = _row_slot(row)
        if slot is not None:
            by_slot[slot] = row
    aligned: list[dict] = []
    for slot in chart.slot_datetimes:
        if slot in by_slot:
            aligned.append(by_slot[slot])
        else:
            aligned.append(_empty_chart_row(slot))
    return aligned


def _hourly_tail_rows(
    sim_rows: list[dict],
    chart: UiChartWindow,
    from_slot: datetime,
) -> tuple[list[dict], tuple[datetime, ...]]:
    aligned = align_rows_to_chart_slots(sim_rows, chart)
    tail_rows: list[dict] = []
    tail_slots: list[datetime] = []
    for slot, row in zip(chart.slot_datetimes, aligned):
        if slot >= from_slot:
            tail_rows.append(row)
            tail_slots.append(slot)
    return tail_rows, tuple(tail_slots)


def _milp_row_for_hour(sim_rows: list[dict], hour_start: datetime) -> dict:
    for row in sim_rows:
        slot = _row_slot(row)
        if slot == hour_start:
            return row
    return _empty_chart_row(hour_start)


def _quarter_row_from_milp(milp_row: dict, slot: datetime) -> dict:
    row = dict(milp_row)
    row["slot_datetime"] = slot
    row["Uhrzeit"] = slot.strftime("%d.%m. %H:%M")
    return row


def _milp_tail_rows(
    chart_context: LiveChartContext,
    sim_rows: list[dict],
    history_end_exclusive: datetime,
) -> tuple[list[dict], tuple[datetime, ...], tuple[str, ...]]:
    """MILP-Zeilen ab history_end_exclusive (1h oder 15-min in laufender Stunde ab x:15)."""
    chart = chart_context.chart_window
    now = chart_context.now
    hour_start = normalize_hour_slot(now)
    next_hour = hour_start + timedelta(hours=1)

    if now.minute < 15:
        rows, slots = _hourly_tail_rows(sim_rows, chart, history_end_exclusive)
        return rows, slots, tuple(SLOT_MILP for _ in rows)

    tail_rows: list[dict] = []
    tail_slots: list[datetime] = []
    if history_end_exclusive < next_hour:
        milp_row = _milp_row_for_hour(sim_rows, hour_start)
        for slot in quarter_hour_slots_between(history_end_exclusive, next_hour):
            if slot > chart.end:
                break
            tail_rows.append(_quarter_row_from_milp(milp_row, slot))
            tail_slots.append(slot)

    if next_hour <= chart.end:
        hourly_rows, hourly_slots = _hourly_tail_rows(sim_rows, chart, next_hour)
        tail_rows.extend(hourly_rows)
        tail_slots.extend(hourly_slots)

    return tail_rows, tuple(tail_slots), tuple(SLOT_MILP for _ in tail_rows)


def _history_gap_notice(result: ChartHistoryResult | None) -> str | None:
    if result is None or not result.rows:
        return None
    if not result.missing_slot_count:
        return None
    return f"{result.missing_slot_count} Viertelstunden-Slots ohne Log-Daten"


def _display_deviation_events(
    history: ChartHistoryResult | None,
    history_slot_count: int,
    total_slot_count: int,
) -> tuple[tuple[DeviationEvent, ...], ...]:
    """Historie-Events + leere Tuples für MILP/neutral/grün."""
    if history is None or history_slot_count <= 0:
        return empty_deviation_series(total_slot_count)
    history_events = history.slot_deviation_events
    if len(history_events) != history_slot_count:
        return empty_deviation_series(total_slot_count)
    tail = empty_deviation_series(total_slot_count - history_slot_count)
    return history_events + tail


def build_chart_display_context(
    chart_context: LiveChartContext,
    sim_rows: list[dict] | None,
) -> ChartDisplayContext:
    """
    Mischt Produktiv-Log (15 min) mit MILP (1 h bzw. 15-min-Soll in laufender Stunde ab x:15).

    Segment SA₁→SA₂: nur MILP. Vergangene SA-Zyklen: nur Log.
    """
    chart = chart_context.chart_window
    rows_input = sim_rows or []
    is_live_segment = (
        chart_context.cycle_offset == 0 and chart_context.segment_index == 0
    )

    if chart.segment_index == 1:
        hourly_rows = align_rows_to_chart_slots(rows_input, chart)
        qualities = tuple(SLOT_MILP for _ in hourly_rows)
        return ChartDisplayContext(
            rows=hourly_rows,
            slot_datetimes=chart.slot_datetimes,
            slot_qualities=qualities,
            history_slot_count=0,
            history_result=None,
            gap_notice=None,
            history_only=False,
            slot_deviation_events=empty_deviation_series(len(hourly_rows)),
        )

    if not is_live_segment:
        history_end = chart.end + timedelta(hours=1)
        history = build_chart_history(chart.start, history_end)
        return ChartDisplayContext(
            rows=history.rows,
            slot_datetimes=history.slot_starts,
            slot_qualities=history.slot_qualities,
            history_slot_count=len(history.rows),
            history_result=history,
            gap_notice=_history_gap_notice(history),
            history_only=True,
            slot_deviation_events=history.slot_deviation_events,
        )

    history_end = history_log_end_exclusive(chart_context.now, chart)
    if history_end <= chart.start:
        milp_rows, milp_slots, milp_qualities = _milp_tail_rows(
            chart_context, rows_input, history_end
        )
        return ChartDisplayContext(
            rows=milp_rows,
            slot_datetimes=milp_slots,
            slot_qualities=milp_qualities,
            history_slot_count=0,
            history_result=None,
            gap_notice=None,
            history_only=False,
            slot_deviation_events=empty_deviation_series(len(milp_rows)),
        )

    history = build_chart_history(chart.start, history_end)
    milp_rows, milp_slots, milp_qualities = _milp_tail_rows(
        chart_context, rows_input, history_end
    )
    qualities = history.slot_qualities + milp_qualities
    total_slots = len(history.rows) + len(milp_rows)
    return ChartDisplayContext(
        rows=history.rows + milp_rows,
        slot_datetimes=history.slot_starts + milp_slots,
        slot_qualities=qualities,
        history_slot_count=len(history.rows),
        history_result=history,
        gap_notice=_history_gap_notice(history),
        history_only=False,
        slot_deviation_events=_display_deviation_events(
            history,
            len(history.rows),
            total_slots,
        ),
    )


def align_rows_to_display_slots(
    sim_rows: list[dict],
    slot_datetimes: tuple[datetime, ...],
) -> list[dict]:
    """Stündliche MILP-Zeilen auf beliebige Display-Slots (inkl. Viertelstunden) abbilden."""
    by_hour: dict[datetime, dict] = {}
    for row in sim_rows:
        slot = _row_slot(row)
        if slot is not None:
            by_hour[slot] = row
    aligned: list[dict] = []
    for slot in slot_datetimes:
        hour = normalize_hour_slot(slot)
        if hour in by_hour:
            row = dict(by_hour[hour])
            row["slot_datetime"] = slot
            row["Uhrzeit"] = slot.strftime("%d.%m. %H:%M")
            aligned.append(row)
        else:
            aligned.append(_empty_chart_row(slot))
    return aligned


def _slots_per_hour(slot_datetimes: tuple[datetime, ...]) -> dict[datetime, int]:
    counts: dict[datetime, int] = {}
    for slot in slot_datetimes:
        hour = normalize_hour_slot(slot)
        counts[hour] = counts.get(hour, 0) + 1
    return counts


def align_hourly_increments_to_display_slots(
    hourly_values: list[float],
    matrix: list[dict],
    chart: UiChartWindow,
    slot_datetimes: tuple[datetime, ...],
) -> list[float]:
    """Stunden-Inkremente gleichmäßig auf Display-Slots der jeweiligen Stunde verteilen."""
    by_hour: dict[datetime, float] = {}
    for index, row in enumerate(matrix):
        slot = _row_slot(row)
        if slot is None or not (chart.start <= slot <= chart.end):
            continue
        if index < len(hourly_values):
            by_hour[slot] = float(hourly_values[index])
    per_hour = _slots_per_hour(slot_datetimes)
    increments: list[float] = []
    for slot in slot_datetimes:
        hour = normalize_hour_slot(slot)
        hourly = by_hour.get(hour, 0.0)
        count = per_hour.get(hour, 1)
        increments.append(hourly / count if count else 0.0)
    return increments


def _actual_slot_increments(
    display_ctx: ChartDisplayContext,
) -> tuple[list[float], list[float]]:
    """Pro-Slot-Ist-Inkremente aus dem Produktiv-Log (fehlende Slots = NaN)."""
    slot_count = len(display_ctx.slot_datetimes)
    cost = [float("nan")] * slot_count
    kwh = [float("nan")] * slot_count
    history = display_ctx.history_result
    if history is None or display_ctx.history_slot_count <= 0:
        return cost, kwh
    for index in range(display_ctx.history_slot_count):
        quality = display_ctx.slot_qualities[index]
        if quality == SLOT_PRESENT:
            cost[index] = history.slot_costs_euro[index]
            kwh[index] = history.slot_consumption_kwh[index]
    return cost, kwh


def build_display_savings_series(
    display_ctx: ChartDisplayContext,
    savings_view: dict,
    matrix: list[dict],
    chart: UiChartWindow,
    *,
    savings_info: dict | None = None,
) -> dict:
    """Kosten-/Verbrauchs-Inkremente auf die gemischte Display-Achse abbilden."""
    slots = display_ctx.slot_datetimes
    view = dict(savings_view)
    matrix_source = savings_info if savings_info is not None else savings_view
    cost_keys = (
        "hourly_matched_baseline_cost_euro",
        "hourly_optimized_cost_euro",
        "hourly_savings_euro",
    )
    kwh_keys = (
        "hourly_matched_baseline_consumption_kwh",
        "hourly_optimized_consumption_kwh",
    )
    for key in cost_keys + kwh_keys:
        values = matrix_source.get(key) or []
        view[key] = align_hourly_increments_to_display_slots(
            values, matrix, chart, slots
        )
    actual_cost, actual_kwh = _actual_slot_increments(display_ctx)
    view["slot_actual_cost_euro"] = actual_cost
    view["slot_actual_consumption_kwh"] = actual_kwh
    return view


def align_hourly_values_to_chart_slots(
    values: list,
    matrix: list[dict],
    chart: UiChartWindow,
    *,
    fill: float = 0.0,
) -> list:
    """Stundenwerte auf chart.slot_datetimes abbilden (fehlende Slots mit fill)."""
    by_slot: dict[datetime, object] = {}
    for index, row in enumerate(matrix):
        slot = _row_slot(row)
        if slot is None or not (chart.start <= slot <= chart.end):
            continue
        if index < len(values):
            by_slot[slot] = values[index]
    return [by_slot.get(slot, fill) for slot in chart.slot_datetimes]


def savings_view_for_chart(
    savings_info: dict,
    matrix: list[dict],
    chart: UiChartWindow,
) -> dict:
    """Stunden-Inkremente auf das Chart-Segment abbilden; Kennzahlen-Summen unverändert."""
    if not matrix_indices_for_chart(matrix, chart):
        return savings_info

    def _pick(key: str) -> list:
        values = savings_info.get(key) or []
        return align_hourly_values_to_chart_slots(values, matrix, chart)

    view = dict(savings_info)
    view["hourly_matched_baseline_cost_euro"] = _pick("hourly_matched_baseline_cost_euro")
    view["hourly_optimized_cost_euro"] = _pick("hourly_optimized_cost_euro")
    view["hourly_savings_euro"] = _pick("hourly_savings_euro")
    view["hourly_matched_baseline_consumption_kwh"] = _pick(
        "hourly_matched_baseline_consumption_kwh"
    )
    view["hourly_optimized_consumption_kwh"] = _pick("hourly_optimized_consumption_kwh")
    return view


def chart_window_label(chart: UiChartWindow) -> str:
    return (
        f"{chart.start.strftime('%d.%m.%Y %H:%M')} – "
        f"{chart.end.strftime('%d.%m.%Y %H:%M')}"
    )


def segment_navigation_label(
    chart: UiChartWindow,
    *,
    cycle_offset: int,
    segment_index: int,
) -> str:
    if segment_index == 0:
        prefix = "SA₀→SA₁ (Live)" if cycle_offset == 0 else "SA₀→SA₁"
    else:
        prefix = "SA₁→SA₂ (Vorausschau)"
    return f"{prefix} · {chart_window_label(chart)}"


def s2_chart_header_label(chart_context: LiveChartContext) -> str:
    """Streamlit-Überschrift für Chart 1 (Segment + optional Zyklus-Hinweis)."""
    label = segment_navigation_label(
        chart_context.chart_window,
        cycle_offset=chart_context.cycle_offset,
        segment_index=chart_context.segment_index,
    )
    if chart_context.cycle_offset > 0:
        label += f" · {chart_context.cycle_offset} Zyklus/Zyklen zurück"
    return label
