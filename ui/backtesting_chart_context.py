"""Backtesting chart window / sunrise-24h context builders."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import os

import pandas as pd
import streamlit as st

import config
from optimizer.charge_immediate import prepare_optimization_matrix
from optimizer.charging_context import serialize_charging_contexts
from optimizer.filter_context import resolve_filter_contexts
from optimizer.simulation import (
    apply_horizon_charging_limits,
    calculate_cost_euro_from_rows,
    hourly_consumption_kwh_from_rows,
    hourly_cost_euro_from_rows,
    hourly_savings_euro_from_rows,
    resolve_horizon_consumer_targets_kwh,
    simulate_baseline_horizon,
    simulate_baseline_with_optimized_flex,
    simulate_matched_baseline_horizon,
    total_consumption_kwh_from_rows,
)
from data.planning_window import (
    UiChartWindow,
    align_to_planning_timezone,
    compute_planning_window,
    compute_sunrise_anchors,
    hourly_slots_inclusive,
    normalize_hour_slot,
    ui_chart_zones,
)
from simulation.backtesting_horizon import window_start_before_anchor
from simulation.backtesting_snapshots import (
    load_window_snapshot,
    snapshot_supports_sunrise_view,
)
from simulation.engine import _scenario_to_battery_params, flex_consumers_from_snapshot
from simulation.horizon_mode import BACKTESTING_STEP_HOURS, FIXED_24H, SUNRISE_WINDOW
from ui.chart_context import LiveChartContext
from ui.history_navigation import s2_zone_help_text
from ui.simulation_results import (
    OptimizationDisplayBundle,
    build_optimization_display_bundle,
)




VIEW_MODE_24H = "24h"

VIEW_MODE_SUNRISE = "sunrise"

_SA_SEGMENT_FORESIGHT = "SA₀→SA₁"

_SA_SEGMENT_BOOK = "SA₁→SA₂"

def sa_segment_date_overlap_hours(
    snapshot: dict,
    selected_date: date,
) -> tuple[int, int]:
    """Hours of chart SA segments that fall on selected_date: (SA₀→SA₁, SA₁→SA₂)."""
    window_anchor = snapshot.get("window_anchor")
    if not window_anchor:
        return 0, 0
    try:
        lat, lon, tz_name = _geo_from_snapshot(snapshot)
        anchor_dt = _parse_window_anchor(str(window_anchor), tz_name)
        planning_moment = window_start_before_anchor(anchor_dt, tz_name)
        foresight = _backtesting_sunrise_segment_window(
            planning_moment, 0, lat, lon, tz_name
        )
        book = _backtesting_sunrise_segment_window(
            planning_moment, 1, lat, lon, tz_name
        )
    except (ValueError, TypeError, KeyError):
        return 0, 0
    foresight_hours = sum(
        1 for slot in foresight.slot_datetimes if slot.date() == selected_date
    )
    book_hours = sum(
        1 for slot in book.slot_datetimes if slot.date() == selected_date
    )
    return foresight_hours, book_hours

def preferred_sa_segment_toggle(snapshot: dict, selected_date: date) -> str:
    """Preselect SA segment with more hourly overlap on the selected calendar date."""
    foresight_hours, book_hours = sa_segment_date_overlap_hours(
        snapshot, selected_date
    )
    if foresight_hours > book_hours:
        return _SA_SEGMENT_FORESIGHT
    return _SA_SEGMENT_BOOK

_SUNRISE_SEGMENT_LABELS = {
    0: _SA_SEGMENT_FORESIGHT,
    1: _SA_SEGMENT_BOOK,
}

def _backtesting_sunrise_header_label(
    window_anchor: str,
    tz_name: str,
    segment_index: int,
) -> str:
    anchor_dt = _parse_window_anchor(window_anchor, tz_name)
    segment = _SUNRISE_SEGMENT_LABELS.get(segment_index, f"Segment {segment_index}")
    return (
        f"Sunrise Backtesting · {anchor_dt.strftime('%d.%m.%Y %H:%M')} · {segment}"
    )

def _parse_slot_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        return ts.to_pydatetime()
    return ts.to_pydatetime()

def _rows_with_parsed_slots(rows: list[dict], tz_name: str) -> list[dict]:
    from optimizer.slot_duration import normalize_quarter_hour_slot

    parsed: list[dict] = []
    for row in rows:
        item = dict(row)
        slot = item.get("slot_datetime")
        if slot is not None:
            item["slot_datetime"] = normalize_quarter_hour_slot(
                align_to_planning_timezone(_parse_slot_datetime(slot), tz_name)
            )
        parsed.append(item)
    return parsed

def _geo_from_snapshot(snapshot: dict) -> tuple[float, float, str]:
    geo = snapshot.get("geo") or {}
    lat = geo.get("latitude")
    lon = geo.get("longitude")
    tz_name = geo.get("timezone") or config.get_planning_timezone()
    if lat is None or lon is None:
        lat = config.get("LATITUDE", cast=float)
        lon = config.get("LONGITUDE", cast=float)
    return float(lat), float(lon), str(tz_name)

def _battery_params_from_snapshot(snapshot: dict) -> dict:
    """Szenario-Batterie aus Snapshot; Fallback für ältere Logs ohne battery_params."""
    stored = snapshot.get("battery_params")
    if isinstance(stored, dict) and float(stored.get("battery_capacity_kwh", 0.0)) > 0:
        return {
            "battery_capacity_kwh": float(stored["battery_capacity_kwh"]),
            "min_soc": float(stored["min_soc"]),
            "max_soc": float(stored["max_soc"]),
            "max_power_kw": float(stored["max_power_kw"]),
            "efficiency": float(stored["efficiency"]),
        }
    scenario_id = str(snapshot.get("scenario_id", ""))
    try:
        scenarios = config.get_backtesting_scenarios()
    except ValueError:
        scenarios = {}
    if scenario_id in scenarios:
        return _scenario_to_battery_params(scenarios[scenario_id])
    live = config.get_battery_params()
    if float(live.get("battery_capacity_kwh", 0.0)) <= 0:
        raise ValueError(
            f"Keine gültigen Batterieparameter für Szenario {scenario_id!r} "
            "(Snapshot ohne battery_params — Backtesting erneut ausführen)."
        )
    return live

def _planning_moment(
    window_anchor: str,
    tz_name: str,
    *,
    view_mode: str,
) -> datetime:
    anchor = pd.Timestamp(window_anchor)
    if anchor.tzinfo is None:
        anchor = anchor.tz_localize(tz_name)
    else:
        anchor = anchor.tz_convert(tz_name)
    anchor_dt = anchor.to_pydatetime()
    if view_mode == VIEW_MODE_SUNRISE:
        moment = window_start_before_anchor(anchor_dt, tz_name)
    else:
        moment = anchor_dt
    return align_to_planning_timezone(moment, tz_name)

def _slot_datetimes_from_sim_rows(
    sim_rows: list[dict],
    tz_name: str,
) -> tuple[datetime, ...]:
    from optimizer.slot_duration import normalize_quarter_hour_slot

    slots: list[datetime] = []
    for row in sim_rows:
        slot = row.get("slot_datetime")
        if slot is None:
            continue
        slots.append(
            normalize_quarter_hour_slot(
                align_to_planning_timezone(_parse_slot_datetime(slot), tz_name)
            )
        )
    if not slots:
        raise ValueError("Keine slot_datetime in Backtesting-Zeilen.")
    return tuple(sorted(set(slots)))

def _parse_window_anchor(window_anchor: str, tz_name: str) -> datetime:
    anchor = pd.Timestamp(window_anchor)
    if anchor.tzinfo is None:
        anchor = anchor.tz_localize(tz_name)
    else:
        anchor = anchor.tz_convert(tz_name)
    return align_to_planning_timezone(anchor.to_pydatetime(), tz_name)

def _backtesting_24h_slots_from_anchor(window_anchor: str, tz_name: str) -> tuple[datetime, ...]:
    """24 wall-clock hours [Anker−24h, Anker) as QH slots (same grid as window_slot_datetimes)."""
    from optimizer.slot_duration import normalize_quarter_hour_slot, slot_step, slots_for_wall_hours

    anchor_dt = _parse_window_anchor(window_anchor, tz_name)
    start = normalize_quarter_hour_slot(window_start_before_anchor(anchor_dt, tz_name))
    step = slot_step()
    n = slots_for_wall_hours(float(BACKTESTING_STEP_HOURS))
    return tuple(start + step * index for index in range(n))

def format_backtesting_window_range(window_anchor: str, tz_name: str) -> str:
    """Lesbares 24h-Fenster [Anker−24h, Anker) — passend zur Chart-X-Achse."""
    anchor_dt = _parse_window_anchor(window_anchor, tz_name)
    start = window_start_before_anchor(anchor_dt, tz_name)
    return (
        f"{start.strftime('%Y-%m-%d %H:%M')} – "
        f"{anchor_dt.strftime('%Y-%m-%d %H:%M')}"
    )

def _backtesting_24h_header_label(window_anchor: str, tz_name: str) -> str:
    anchor_dt = _parse_window_anchor(window_anchor, tz_name)
    start = window_start_before_anchor(anchor_dt, tz_name)
    return (
        f"24h Backtesting · {start.strftime('%d.%m.%Y %H:%M')} – "
        f"{anchor_dt.strftime('%d.%m.%Y %H:%M')}"
    )

def _backtesting_sunrise_segment_window(
    planning_moment: datetime,
    segment_index: int,
    lat: float,
    lon: float,
    tz_name: str,
) -> UiChartWindow:
    """
    SA-Segment für Backtesting: ab Planungsstart (Anker−24h), nicht ab astronomischem SA₀.

    Live S-2 zeigt SA₀→SA₁ ab letztem Sonnenaufgang; Backtesting-Daten beginnen erst
    am Planungsstart — Slots davor wären leer und verschieben die X-Achse fälschlich.
    """
    if segment_index not in (0, 1):
        raise ValueError(
            f"segment_index muss 0 oder 1 sein, erhalten: {segment_index}."
        )
    planning_window = compute_planning_window(
        planning_moment,
        lat,
        lon,
        tz_name,
    )
    anchors = compute_sunrise_anchors(planning_moment, lat, lon, tz_name)
    if segment_index == 0:
        seg_start = planning_moment
        seg_end = anchors.sa1
    else:
        seg_start = anchors.sa1
        seg_end = anchors.sa2
    seg_start = normalize_hour_slot(max(seg_start, planning_window.start))
    seg_end = normalize_hour_slot(min(seg_end, planning_window.end))
    if seg_start > seg_end:
        raise ValueError(
            f"Backtesting-SA-Segment {segment_index} leer: "
            f"{seg_start} liegt nach {seg_end}."
        )
    slots = tuple(hourly_slots_inclusive(seg_start, seg_end))
    return UiChartWindow(
        start=seg_start,
        end=seg_end,
        sa0=anchors.sa0,
        sa1=anchors.sa1,
        sa2=anchors.sa2,
        segment_index=segment_index,
        slot_datetimes=slots,
    )

def _build_backtesting_sunrise_chart_context(
    *,
    window_anchor: str,
    segment_index: int,
    sim_rows: list[dict],
    geo: tuple[float, float, str],
) -> LiveChartContext:
    lat, lon, tz_name = geo
    anchor_dt = _parse_window_anchor(window_anchor, tz_name)
    planning_moment = window_start_before_anchor(anchor_dt, tz_name)
    chart = _backtesting_sunrise_segment_window(
        planning_moment,
        segment_index,
        lat,
        lon,
        tz_name,
    )
    zone_reference = chart.end
    zones = ui_chart_zones(
        zone_reference,
        chart,
        sim_rows=sim_rows,
        is_live_segment=False,
    )
    return LiveChartContext(
        now=planning_moment,
        chart_window=chart,
        zones=zones,
        cycle_offset=0,
        segment_index=segment_index,
        zone_reference=zone_reference,
        planning_window=None,
    )

def _build_backtesting_24h_chart_context(
    *,
    window_anchor: str,
    sim_rows: list[dict],
    geo: tuple[float, float, str],
) -> LiveChartContext:
    """24h-Backtesting-Fenster [Anker−24h, Anker) — ohne S-2-SA-Segment."""
    lat, lon, tz_name = geo
    anchor_dt = _parse_window_anchor(window_anchor, tz_name)
    slots = _backtesting_24h_slots_from_anchor(window_anchor, tz_name)
    row_slots = _slot_datetimes_from_sim_rows(sim_rows, tz_name)
    if row_slots != slots:
        raise ValueError(
            f"Backtesting-Snapshot-Slots weichen vom Fenster-Anker ab: "
            f"Anker {window_anchor!r} erwartet {slots[0]}..{slots[-1]}, "
            f"Snapshot {row_slots[0]}..{row_slots[-1]}."
        )
    start = slots[0]
    planning_moment = start
    anchors = compute_sunrise_anchors(start, lat, lon, tz_name)
    chart = UiChartWindow(
        start=start,
        end=anchor_dt,
        sa0=anchors.sa0,
        sa1=anchors.sa1,
        sa2=anchors.sa2,
        segment_index=0,
        slot_datetimes=slots,
    )
    zones = ui_chart_zones(
        anchor_dt,
        chart,
        sim_rows=sim_rows,
        is_live_segment=False,
    )
    return LiveChartContext(
        now=planning_moment,
        chart_window=chart,
        zones=zones,
        cycle_offset=0,
        segment_index=0,
        zone_reference=anchor_dt,
        planning_window=None,
    )

def build_backtesting_chart_context(
    window_anchor: str,
    *,
    view_mode: str,
    segment_index: int,
    sim_rows: list[dict],
    geo: tuple[float, float, str] | None = None,
) -> LiveChartContext:
    lat, lon, tz_name = geo or (
        config.get("LATITUDE", cast=float),
        config.get("LONGITUDE", cast=float),
        config.get_planning_timezone(),
    )
    if view_mode == VIEW_MODE_24H:
        return _build_backtesting_24h_chart_context(
            window_anchor=window_anchor,
            sim_rows=sim_rows,
            geo=(lat, lon, tz_name),
        )
    return _build_backtesting_sunrise_chart_context(
        window_anchor=window_anchor,
        segment_index=segment_index,
        sim_rows=sim_rows,
        geo=(lat, lon, tz_name),
    )
