"""Laden persistierter Cockpit-Anzeigedaten aus live_optimization_debug.json."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from data.planning_window import PlanningWindow, parse_row_slot_datetime
from optimizer import schedule as optimization_schedule
from runtime_store import live_optimization_debug

PERSISTED_DISPLAY_MAX_AGE_SECONDS = optimization_schedule.PERSISTED_DISPLAY_MAX_AGE_SECONDS


def snapshot_completed_at(snapshot: dict[str, Any] | None) -> str | None:
    """Zeitstempel des Snapshots (completed_at oder main_run_completed_at)."""
    if not snapshot:
        return None
    raw = snapshot.get("completed_at") or snapshot.get("main_run_completed_at")
    return str(raw) if raw else None


def snapshot_age_seconds(
    completed_at: str | None,
    now: datetime | None = None,
) -> float | None:
    return optimization_schedule.snapshot_age_seconds(completed_at, now)


def is_persisted_display_fresh(
    completed_at: str | None,
    now: datetime | None = None,
    *,
    max_age_sec: int = PERSISTED_DISPLAY_MAX_AGE_SECONDS,
) -> bool:
    return optimization_schedule.is_persisted_display_fresh(
        completed_at,
        now,
        max_age_sec=max_age_sec,
    )


def load_live_display_snapshot() -> dict[str, Any] | None:
    """Letzten Live-Debug-Snapshot laden."""
    return live_optimization_debug.load_debug_snapshot(kind="live")


def _normalize_matrix_rows(rows: list) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        slot_dt = parse_row_slot_datetime(row)
        if slot_dt is not None:
            item["slot_datetime"] = slot_dt
        normalized.append(item)
    return normalized


def _simulation_rows_support_hourly_series(rows: list[dict]) -> bool:
    if not rows:
        return False
    sample = rows[0]
    return (
        "Strompreis (Cent/kWh)" in sample
        and "Verbrauch-Prognose (kW)" in sample
    )


def _attach_hourly_series_from_rows(
    savings_info: dict[str, Any],
    *,
    optimized_rows: list[dict],
    matched_rows: list[dict],
) -> None:
    """Stunden-Inkremente aus persistierten Sim-Zeilen, falls nicht im Snapshot."""
    if not _simulation_rows_support_hourly_series(optimized_rows):
        return
    from optimizer.simulation import (
        hourly_consumption_kwh_from_rows,
        hourly_cost_euro_from_rows,
        hourly_savings_euro_from_rows,
    )

    if "hourly_optimized_cost_euro" not in savings_info:
        savings_info["hourly_optimized_cost_euro"] = hourly_cost_euro_from_rows(
            optimized_rows
        )
    if matched_rows and _simulation_rows_support_hourly_series(matched_rows):
        if "hourly_matched_baseline_cost_euro" not in savings_info:
            savings_info["hourly_matched_baseline_cost_euro"] = hourly_cost_euro_from_rows(
                matched_rows
            )
        if "hourly_savings_euro" not in savings_info:
            savings_info["hourly_savings_euro"] = hourly_savings_euro_from_rows(
                matched_rows,
                optimized_rows,
            )
        if "hourly_matched_baseline_consumption_kwh" not in savings_info:
            savings_info["hourly_matched_baseline_consumption_kwh"] = (
                hourly_consumption_kwh_from_rows(matched_rows)
            )


def savings_info_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """savings_info-Form aus persistiertem Debug-Snapshot rekonstruieren."""
    savings = snapshot.get("savings") or {}
    optimized_rows = snapshot.get("simulation_rows") or []
    matched_rows = snapshot.get("matched_baseline_rows") or []
    same_flex_rows = snapshot.get("baseline_same_flex_rows") or []
    savings_info = {
        "baseline_cost_euro": savings.get("baseline_cost_euro"),
        "matched_baseline_cost_euro": savings.get("matched_baseline_cost_euro"),
        "optimized_cost_euro": savings.get("optimized_cost_euro"),
        "savings_euro": savings.get("savings_euro"),
        "savings_matched_euro": savings.get("savings_matched_euro"),
        "baseline_consumption_kwh": savings.get("baseline_consumption_kwh"),
        "matched_baseline_consumption_kwh": savings.get("matched_baseline_consumption_kwh"),
        "optimized_consumption_kwh": savings.get("optimized_consumption_kwh"),
        "baseload_kwh": savings.get("baseload_kwh"),
        "optimized_rows": optimized_rows,
        "baseline_rows": snapshot.get("baseline_rows") or [],
        "matched_baseline_rows": matched_rows,
        "baseline_same_flex_rows": same_flex_rows,
        "applied_targets": snapshot.get("applied_targets") or [],
        "energy_comparison": snapshot.get("energy_comparison") or [],
    }
    for key in (
        "hourly_matched_baseline_cost_euro",
        "hourly_optimized_cost_euro",
        "hourly_savings_euro",
        "hourly_matched_baseline_consumption_kwh",
        "hourly_optimized_consumption_kwh",
    ):
        if key in savings:
            savings_info[key] = savings[key]
    _attach_hourly_series_from_rows(
        savings_info,
        optimized_rows=optimized_rows,
        matched_rows=matched_rows,
    )
    return savings_info


def planning_matrix_from_snapshot(snapshot: dict[str, Any]) -> list[dict]:
    matrix = snapshot.get("planning_matrix")
    if isinstance(matrix, list) and matrix:
        return _normalize_matrix_rows(matrix)
    simulation_rows = snapshot.get("simulation_rows")
    if isinstance(simulation_rows, list) and simulation_rows:
        return _normalize_matrix_rows(simulation_rows)
    return []


def planning_window_from_snapshot(snapshot: dict[str, Any]) -> PlanningWindow | None:
    """PlanningWindow aus Snapshot-Metadaten; None wenn nicht vorhanden."""
    raw = snapshot.get("planning_window")
    if not isinstance(raw, dict):
        return None
    try:
        tz_name = str(raw["timezone_name"])
        start = datetime.fromisoformat(str(raw["start"]))
        end = datetime.fromisoformat(str(raw["end"]))
        sunset_1 = datetime.fromisoformat(str(raw["sunset_1"]))
        sunset_2 = datetime.fromisoformat(str(raw["sunset_2"]))
        sunrise = datetime.fromisoformat(str(raw["sunrise_anchor"]))
        slots_raw = raw.get("slot_datetimes") or []
        slot_datetimes = tuple(datetime.fromisoformat(str(item)) for item in slots_raw)
        return PlanningWindow(
            start=start,
            end=end,
            sunset_1=sunset_1,
            sunset_2=sunset_2,
            sunrise_anchor=sunrise,
            slot_datetimes=slot_datetimes,
            timezone_name=tz_name,
            latitude=float(raw.get("latitude", 0.0)),
            longitude=float(raw.get("longitude", 0.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def serialize_planning_window(window: PlanningWindow) -> dict[str, Any]:
    """PlanningWindow für JSON-Persistenz."""
    return {
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "sunset_1": window.sunset_1.isoformat(),
        "sunset_2": window.sunset_2.isoformat(),
        "sunrise_anchor": window.sunrise_anchor.isoformat(),
        "slot_datetimes": [slot.isoformat() for slot in window.slot_datetimes],
        "timezone_name": window.timezone_name,
        "latitude": window.latitude,
        "longitude": window.longitude,
        "horizon_hours": window.horizon_hours,
    }
