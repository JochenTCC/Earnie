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


def savings_info_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """savings_info-Form aus persistiertem Debug-Snapshot rekonstruieren."""
    savings = snapshot.get("savings") or {}
    return {
        "baseline_cost_euro": savings.get("baseline_cost_euro"),
        "matched_baseline_cost_euro": savings.get("matched_baseline_cost_euro"),
        "optimized_cost_euro": savings.get("optimized_cost_euro"),
        "savings_euro": savings.get("savings_euro"),
        "savings_matched_euro": savings.get("savings_matched_euro"),
        "baseline_consumption_kwh": savings.get("baseline_consumption_kwh"),
        "matched_baseline_consumption_kwh": savings.get("matched_baseline_consumption_kwh"),
        "optimized_consumption_kwh": savings.get("optimized_consumption_kwh"),
        "baseload_kwh": savings.get("baseload_kwh"),
        "optimized_rows": snapshot.get("simulation_rows") or [],
        "baseline_rows": snapshot.get("baseline_rows") or [],
        "matched_baseline_rows": snapshot.get("matched_baseline_rows") or [],
        "applied_targets": snapshot.get("applied_targets") or [],
        "energy_comparison": snapshot.get("energy_comparison") or [],
    }


def planning_matrix_from_snapshot(snapshot: dict[str, Any]) -> list[dict]:
    matrix = snapshot.get("planning_matrix")
    if not isinstance(matrix, list):
        return []
    normalized: list[dict] = []
    for row in matrix:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        slot_dt = parse_row_slot_datetime(row)
        if slot_dt is not None:
            item["slot_datetime"] = slot_dt
        normalized.append(item)
    return normalized


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
