"""Swimspa-Zeitreihen für die Verbraucheranalyse aus optimization_history.jsonl."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from data.planning_window import history_log_end_exclusive
from optimizer.filter_context import slot_in_native_window
from runtime_store.history_timeline import (
    _build_rows_for_slot_starts,
    _coerce_slot_start,
    _format_slot_time,
    quarter_hour_slots_between,
)
from ui.chart_context import build_live_chart_context, live_now

SWIMSPA_ID = "swimspa"
FILTER_ID = "swimspa_filter"


@dataclass(frozen=True)
class SwimspaAnalysisData:
    temperature_df: pd.DataFrame
    filter_df: pd.DataFrame
    zones: object
    gap_notice: str | None


def _flex_filter_kw(entry: dict) -> float:
    snapshot = entry.get("consumption_snapshot") or {}
    flex_kw = snapshot.get("flex_kw") or {}
    if FILTER_ID in flex_kw:
        return float(flex_kw[FILTER_ID] or 0.0)
    live = entry.get("flex_live_kw") or {}
    return float(live.get(FILTER_ID, 0.0) or 0.0)


def _split_filter_kw(entry: dict, slot_start: datetime, power_kw: float) -> tuple[float, float]:
    if power_kw <= 0:
        return 0.0, 0.0
    ctx = (entry.get("filter_contexts") or {}).get(FILTER_ID) or {}
    start_hour = ctx.get("native_start_hour")
    duration = ctx.get("native_duration_hours")
    if start_hour is not None and duration is not None:
        if slot_in_native_window(slot_start, float(start_hour), float(duration)):
            return power_kw, 0.0
    return 0.0, power_kw


def _thermal_readings(entry: dict) -> tuple[float | None, float | None]:
    for item in entry.get("thermal_observability") or []:
        if not isinstance(item, dict):
            continue
        if item.get("consumer_id") != SWIMSPA_ID:
            continue
        readings = item.get("readings_c") or {}
        actual = readings.get("actual")
        setpoint = readings.get("setpoint")
        return (
            None if actual is None else float(actual),
            None if setpoint is None else float(setpoint),
        )
    return None, None


def build_swimspa_analysis_data(
    *,
    cycle_offset: int = 0,
    segment_index: int = 0,
    now: datetime | None = None,
) -> SwimspaAnalysisData | None:
    moment = now or live_now()
    ctx = build_live_chart_context(cycle_offset, segment_index, now=moment)
    chart = ctx.chart_window
    if segment_index == 1:
        return None

    if cycle_offset == 0 and segment_index == 0:
        history_end = history_log_end_exclusive(moment, chart)
    else:
        history_end = chart.end + timedelta(hours=1)

    if history_end <= chart.start:
        return None

    slot_starts = quarter_hour_slots_between(chart.start, history_end)
    _, qualities, _, _, missing, by_slot = _build_rows_for_slot_starts(
        slot_starts,
        include_date=True,
        hold_forward=False,
    )

    temp_rows: list[dict] = []
    filter_rows: list[dict] = []
    for slot_start, quality in zip(slot_starts, qualities):
        slot_key = _coerce_slot_start(slot_start)
        entry = by_slot.get(slot_key)
        label = _format_slot_time(slot_start, include_date=True)
        actual_c, setpoint_c = _thermal_readings(entry) if entry else (None, None)
        temp_rows.append(
            {
                "slot_datetime": slot_start,
                "Uhrzeit": label,
                "Ist (°C)": actual_c,
                "Soll (°C)": setpoint_c,
            }
        )
        autonom_kw = ernie_kw = 0.0
        if entry is not None:
            power = _flex_filter_kw(entry)
            autonom_kw, ernie_kw = _split_filter_kw(entry, slot_start, power)
        filter_rows.append(
            {
                "slot_datetime": slot_start,
                "Uhrzeit": label,
                "Autonom (kW)": round(autonom_kw, 3),
                "Earnie (kW)": round(ernie_kw, 3),
            }
        )

    gap = None
    if missing:
        gap = f"{missing} von {len(slot_starts)} Slots ohne Log-Daten"
    return SwimspaAnalysisData(
        temperature_df=pd.DataFrame(temp_rows),
        filter_df=pd.DataFrame(filter_rows),
        zones=ctx.zones,
        gap_notice=gap,
    )
