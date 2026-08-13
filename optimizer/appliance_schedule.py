"""Manuelle Geräte: fixe Zusatzlast in der Planungsmatrix und Chart-Darstellung."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from data.planning_window import align_to_planning_timezone
import config
from optimizer.slot_duration import DEFAULT_DT_H

CHART_KIND_MANUAL_APPLIANCE = "manual_appliance"
_EPS_H = 1e-9


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


def _infer_rows_dt_h(rows: list[dict[str, Any]]) -> float:
    prev = None
    for row in rows:
        moment = _slot_datetime(row)
        if moment is None:
            continue
        if prev is not None:
            delta_h = (moment - prev).total_seconds() / 3600.0
            if delta_h > _EPS_H:
                return delta_h
        prev = moment
    return DEFAULT_DT_H


def _neighbor_dt_h(moments: list[datetime | None], index: int) -> float:
    current = moments[index]
    if current is None:
        return DEFAULT_DT_H
    if index + 1 < len(moments) and moments[index + 1] is not None:
        delta_h = (moments[index + 1] - current).total_seconds() / 3600.0
        if delta_h > _EPS_H:
            return delta_h
    if index > 0 and moments[index - 1] is not None:
        delta_h = (current - moments[index - 1]).total_seconds() / 3600.0
        if delta_h > _EPS_H:
            return delta_h
    return DEFAULT_DT_H


def _power_fraction(
    slot_start: datetime,
    schedule_start: datetime,
    runtime_h: float,
    slot_dt_h: float,
) -> float:
    slot_end = slot_start + timedelta(hours=slot_dt_h)
    run_end = schedule_start + timedelta(hours=runtime_h)
    overlap_start = max(slot_start, schedule_start)
    overlap_end = min(slot_end, run_end)
    if overlap_end <= overlap_start:
        return 0.0
    overlap_h = (overlap_end - overlap_start).total_seconds() / 3600.0
    return min(1.0, overlap_h / slot_dt_h)


def apply_appliance_schedules_to_matrix(
    matrix: list[dict[str, Any]],
    schedules: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Rechnet geplante manuelle Geräte als Zusatz auf expected_p_act ein."""
    if not matrix or not schedules:
        return matrix

    updated = copy.deepcopy(matrix)
    slot_dt_h = _infer_rows_dt_h(updated)
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
        for row in updated:
            slot_start = _slot_datetime(row)
            if slot_start is None:
                continue
            fraction = _power_fraction(slot_start, start_at, runtime_h, slot_dt_h)
            if fraction <= 0:
                continue
            add_kw = round(power_kw * fraction, 3)
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
    slot_dt_h: float | None = None,
) -> dict[str, float]:
    """Geplante Leistung (kW) je Gerät für einen Slotbeginn."""
    lookup = appliances_by_id if appliances_by_id is not None else _appliances_by_id()
    if not schedules or not lookup:
        return {}
    dt_h = DEFAULT_DT_H if slot_dt_h is None else float(slot_dt_h)
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
        fraction = _power_fraction(slot_start, start_at, runtime_h, dt_h)
        if fraction <= 0:
            continue
        kw = round(power_kw * fraction, 2)
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

    slot_times = [_slot_datetime(chart_row) for chart_row in chart_rows]
    for index, chart_row in enumerate(chart_rows):
        slot_start = slot_times[index]
        if slot_start is None:
            continue
        by_id = appliance_kw_for_slot(
            slot_start,
            schedules,
            appliances_by_id=appliances_by_id,
            slot_dt_h=_neighbor_dt_h(slot_times, index),
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
