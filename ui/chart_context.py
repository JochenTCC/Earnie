"""Live-Chart: sunrise→sunrise-Fenster, Zonen und Kosten-Summen."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from data.planning_window import (
    PlanningWindow,
    UiChartWindow,
    UiChartZones,
    compute_ui_chart_window_with_offset,
    normalize_hour_slot,
    ui_chart_zones,
)


@dataclass(frozen=True)
class LiveChartContext:
    """Darstellungskontext für den Live-Optimierungschart."""

    now: datetime
    chart_window: UiChartWindow
    zones: UiChartZones
    ui_offset_cycles: int
    zone_reference: datetime
    planning_window: PlanningWindow | None = None


def live_now() -> datetime:
    tz = ZoneInfo(config.get_planning_timezone())
    return datetime.now(tz).replace(minute=0, second=0, microsecond=0)


def build_live_chart_context(
    ui_offset_cycles: int,
    *,
    now: datetime | None = None,
    planning_window: PlanningWindow | None = None,
) -> LiveChartContext:
    if ui_offset_cycles < 0:
        raise ValueError(f"ui_offset_cycles muss >= 0 sein, erhalten: {ui_offset_cycles}.")
    moment = now if now is not None else live_now()
    if moment.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    lat = config.get("LATITUDE", cast=float)
    lon = config.get("LONGITUDE", cast=float)
    tz_name = config.get_planning_timezone()
    chart = compute_ui_chart_window_with_offset(
        moment, ui_offset_cycles, lat, lon, tz_name
    )
    reference = moment if ui_offset_cycles == 0 else chart.end
    zones = ui_chart_zones(reference, chart)
    return LiveChartContext(
        now=moment,
        chart_window=chart,
        zones=zones,
        ui_offset_cycles=ui_offset_cycles,
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
        return [values[i] for i in indices if i < len(values)]

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
