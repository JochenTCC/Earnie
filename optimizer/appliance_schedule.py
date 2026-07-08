"""Manuelle Geräte: fixe Zusatzlast in der Planungsmatrix."""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from data.planning_window import align_to_planning_timezone, normalize_hour_slot
import config
from optimizer.appliance_recommendation import _slot_run_weights


def _planning_tz() -> str:
    return config.get_planning_timezone()


def _slot_datetime(row: dict[str, Any]) -> datetime | None:
    raw = row.get("slot_datetime") or row.get("date")
    if raw is None:
        return None
    tz = _planning_tz()
    if isinstance(raw, datetime):
        return align_to_planning_timezone(raw, tz)
    return align_to_planning_timezone(datetime.fromisoformat(str(raw)), tz)


def _weight_for_slot(
    slot_start: datetime,
    schedule_start: datetime,
    weights: list[float],
) -> float:
    delta_h = (normalize_hour_slot(slot_start) - normalize_hour_slot(schedule_start)).total_seconds() / 3600.0
    index = int(round(delta_h))
    if index < 0 or index >= len(weights):
        return 0.0
    return float(weights[index])


def apply_appliance_schedules_to_matrix(
    matrix: list[dict[str, Any]],
    schedules: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Rechnet geplante manuelle Geräte als Zusatz auf expected_p_act ein."""
    if not matrix or not schedules:
        return matrix

    updated = copy.deepcopy(matrix)
    for entry in schedules.values():
        start_raw = entry.get("start_at")
        if not start_raw:
            continue
        start_at = align_to_planning_timezone(
            datetime.fromisoformat(str(start_raw)), _planning_tz()
        )
        power_kw = float(entry.get("power_kw", 0.0) or 0.0)
        runtime_h = float(entry.get("runtime_h", 0.0) or 0.0)
        if power_kw <= 0 or runtime_h <= 0:
            continue
        weights = _slot_run_weights(runtime_h)
        for row in updated:
            slot_start = _slot_datetime(row)
            if slot_start is None:
                continue
            weight = _weight_for_slot(slot_start, start_at, weights)
            if weight <= 0:
                continue
            add_kw = round(power_kw * weight, 3)
            row["expected_p_act"] = round(float(row.get("expected_p_act", 0.0)) + add_kw, 3)
            flex = dict(row.get("expected_flex_kw") or {})
            total_flex = sum(float(v or 0.0) for v in flex.values())
            row["expected_p_total"] = round(float(row.get("expected_p_act", 0.0)) + total_flex, 3)
    return updated
