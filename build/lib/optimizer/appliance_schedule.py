"""Manuelle Geräte: fixe Zusatzlast in der Planungsmatrix und Chart-Darstellung."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from data.planning_window import align_to_planning_timezone, normalize_hour_slot
import config
from optimizer.appliance_recommendation import _slot_run_weights

CHART_KIND_MANUAL_APPLIANCE = "manual_appliance"


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


def appliance_column_name(appliance: Mapping[str, Any]) -> str:
    return f"{appliance['name']} (kW)"


def appliance_as_chart_consumer(appliance: Mapping[str, Any]) -> dict[str, Any]:
    """Chart-Stack-Eintrag für ein manuelles Gerät (gemeinsame Farbe, eigener Hover-Name)."""
    return {**dict(appliance), "chart_kind": CHART_KIND_MANUAL_APPLIANCE}


def is_manual_appliance_chart_consumer(consumer: Mapping[str, Any]) -> bool:
    return consumer.get("chart_kind") == CHART_KIND_MANUAL_APPLIANCE


def _appliances_by_id() -> dict[str, dict[str, Any]]:
    return {str(appliance["id"]): appliance for appliance in config.get_appliances()}


def appliance_kw_for_slot(
    slot_start: datetime,
    schedules: dict[str, dict[str, Any]],
    *,
    appliances_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Geplante Leistung (kW) je Gerät für einen Slotbeginn."""
    lookup = appliances_by_id if appliances_by_id is not None else _appliances_by_id()
    if not schedules or not lookup:
        return {}
    result: dict[str, float] = {}
    for appliance_id, entry in schedules.items():
        appliance = lookup.get(str(appliance_id))
        if appliance is None:
            continue
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
        weight = _weight_for_slot(
            slot_start,
            start_at,
            _slot_run_weights(runtime_h),
        )
        if weight <= 0:
            continue
        kw = round(power_kw * weight, 2)
        if kw > 0:
            result[str(appliance_id)] = kw
    return result


def _recalculate_chart_row_grid(chart_row: dict[str, Any]) -> None:
    from optimizer.targets import consumer_column_name

    pv = float(chart_row.get("PV-Prognose (kW)", 0.0) or 0.0)
    batt = float(chart_row.get("Geplante Batterie-Aktion (kW)", 0.0) or 0.0)
    flex_sum = sum(
        float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
        for consumer in config.get_flexible_consumers(optimizer_only=True)
    )
    for appliance in config.get_appliances():
        flex_sum += float(chart_row.get(appliance_column_name(appliance), 0.0) or 0.0)
    con = float(chart_row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
    chart_row["Netzbezug (kW)"] = round(con + flex_sum - pv + batt, 2)


def apply_appliance_schedules_to_chart_rows(
    chart_rows: list[dict[str, Any]],
    schedules: dict[str, dict[str, Any]] | None = None,
) -> None:
    """
    Zeigt geplante manuelle Geräte als eigene Flex-Spuren (nicht in Grundlast).

    Physik (Netzbezug vor dem Aufruf) bleibt unverändert; nur die Darstellung wird
    aufgeteilt wie bei Sofort-Laden.
    """
    if not chart_rows:
        return
    if schedules is None:
        from runtime_store.appliance_schedules import purge_expired

        schedules = purge_expired()
    appliances_by_id = _appliances_by_id()
    if not schedules or not appliances_by_id:
        return

    for chart_row in chart_rows:
        slot_start = _slot_datetime(chart_row)
        if slot_start is None:
            continue
        by_id = appliance_kw_for_slot(
            slot_start,
            schedules,
            appliances_by_id=appliances_by_id,
        )
        moved_kw = 0.0
        for appliance_id, kw in by_id.items():
            appliance = appliances_by_id[appliance_id]
            chart_row[appliance_column_name(appliance)] = kw
            moved_kw += kw
        if moved_kw <= 1e-6:
            continue
        chart_row["Verbrauch-Prognose (kW)"] = round(
            float(chart_row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0) - moved_kw,
            2,
        )
        _recalculate_chart_row_grid(chart_row)
