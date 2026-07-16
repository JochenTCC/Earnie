"""Chart-1 display peel for earnie_role=known generics (Grundlast → named traces)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from house_config.generic_schedule import generic_hourly_kw_for_day
from house_config.planning_flex_bridge import (
    _allocate_chart_color_index,
    _used_chart_color_indices,
    split_planning_generic_consumers,
)


def _resolve_house_profile(house_profile: dict | None) -> dict:
    if house_profile is not None:
        return house_profile
    import config

    return (config.get_resolved_runtime_settings() or {}).get("_house_profile") or {}


def _slot_datetime(row: dict[str, Any]) -> datetime | None:
    raw = row.get("slot_datetime") or row.get("date")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def known_column_name(consumer: dict) -> str:
    label = str(consumer.get("label") or consumer.get("name") or consumer["id"])
    return f"{label} (kW)"


def known_as_chart_consumer(
    consumer: dict,
    *,
    chart_color_index: int,
) -> dict[str, Any]:
    """MILP-free Chart-stack entry for a known generic consumer."""
    return {
        "id": str(consumer["id"]),
        "name": str(consumer.get("label") or consumer["id"]),
        "chart_color_index": int(chart_color_index),
    }


def chart_known_generics(
    house_profile: dict | None = None,
    *,
    used_color_indices: set[int] | None = None,
) -> list[dict]:
    """Known generics as Chart consumers with allocated palette indices."""
    profile = _resolve_house_profile(house_profile)
    fixed, _flex = split_planning_generic_consumers(profile)
    if not fixed:
        return []
    used = set(used_color_indices or ())
    used |= _used_chart_color_indices(fixed)
    result: list[dict] = []
    for consumer in fixed:
        consumer_id = str(consumer["id"])
        legacy_id = str(consumer.get("legacy_id") or "").strip() or None
        raw = consumer.get("chart_color_index")
        if raw is None:
            index = _allocate_chart_color_index(
                used, consumer_id, legacy_id=legacy_id
            )
        else:
            try:
                index = int(raw)
            except (TypeError, ValueError):
                index = _allocate_chart_color_index(
                    used, consumer_id, legacy_id=legacy_id
                )
        used.add(index)
        result.append(known_as_chart_consumer(consumer, chart_color_index=index))
    return result


def apply_known_generic_to_chart_rows(
    chart_rows: list[dict[str, Any]],
    *,
    house_profile: dict | None = None,
) -> None:
    """
    Split known schedule power out of Verbrauch-Prognose into named kW columns.

    Optimization still treats known as Grundlast; this is display-only (like
    ``apply_appliance_schedules_to_chart_rows``).
    """
    if not chart_rows:
        return
    profile = _resolve_house_profile(house_profile)
    fixed, _flex = split_planning_generic_consumers(profile)
    if not fixed:
        return

    for chart_row in chart_rows:
        slot = _slot_datetime(chart_row)
        if slot is None:
            continue
        day_hourly_by_id = {
            str(consumer["id"]): generic_hourly_kw_for_day(consumer, slot.date())
            for consumer in fixed
        }
        moved_kw = 0.0
        for consumer in fixed:
            col = known_column_name(consumer)
            scheduled = float(day_hourly_by_id[str(consumer["id"])][slot.hour])
            if scheduled <= 1e-9:
                continue
            if float(chart_row.get(col, 0.0) or 0.0) > 1e-9:
                continue
            chart_row[col] = round(scheduled, 3)
            moved_kw += scheduled
        if moved_kw <= 1e-6:
            continue
        baseload = float(chart_row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
        chart_row["Verbrauch-Prognose (kW)"] = round(max(0.0, baseload - moved_kw), 3)


def apply_known_generic_to_dataframe(
    df: pd.DataFrame,
    *,
    house_profile: dict | None = None,
) -> pd.DataFrame:
    """DataFrame wrapper for Chart-1 known peel."""
    if df is None or df.empty:
        return df
    rows = df.to_dict(orient="records")
    apply_known_generic_to_chart_rows(rows, house_profile=house_profile)
    out = pd.DataFrame.from_records(rows)
    # Keep original column order; append new known columns at the end.
    original = list(df.columns)
    extra = [col for col in out.columns if col not in original]
    return out.reindex(columns=original + extra)
