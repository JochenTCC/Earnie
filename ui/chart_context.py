"""Live-Chart: S-2-Segmente SA₀→SA₁ / SA₁→SA₂, Zonen und Kosten-Summen."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from data.planning_window import (
    PlanningWindow,
    UiChartWindow,
    UiChartZones,
    compute_ui_chart_window,
    normalize_hour_slot,
    normalize_planning_hour_slot,
    ui_chart_zones,
)
from runtime_store import optimization_history


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
    return datetime.now(tz).replace(minute=0, second=0, microsecond=0)


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
    zones = ui_chart_zones(zone_now, chart, sim_rows=sim_rows)
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
    """Kosten-Summen und Stundenlisten auf das sunrise→sunrise-Fenster beschränken."""
    indices = matrix_indices_for_chart(matrix, chart)
    if not indices:
        return savings_info

    def _pick(key: str) -> list:
        values = savings_info.get(key) or []
        return align_hourly_values_to_chart_slots(values, matrix, chart)

    hourly_matched = _pick("hourly_matched_baseline_cost_euro")
    hourly_optimized = _pick("hourly_optimized_cost_euro")
    matched_total = round(sum(hourly_matched), 4)
    optimized_total = round(sum(hourly_optimized), 4)
    view = dict(savings_info)
    view["matched_baseline_cost_euro"] = matched_total
    view["optimized_cost_euro"] = optimized_total
    view["savings_matched_euro"] = round(matched_total - optimized_total, 4)
    view["hourly_matched_baseline_cost_euro"] = hourly_matched
    view["hourly_optimized_cost_euro"] = hourly_optimized
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
