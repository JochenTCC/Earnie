"""
live_consumption.py – Read-only Live-Snapshot aus Loxone für app.py (Sankey, What-if).

Schreibt keine cons_data; nur Lesen über loxone_client.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import config
from integrations import loxone_client
from optimizer.filter_context import filter_schedule_enabled

logger = logging.getLogger(__name__)

_UI_TIMEZONE = ZoneInfo("Europe/Vienna")


def build_consumption_snapshot(
    live_power: dict[str, float],
    flex_kw: dict[str, float],
) -> dict[str, Any]:
    """Snapshot aus bereits gelesenen Live-Werten (kein weiterer API-Call)."""
    flex_sum = round(sum(flex_kw.values()), 3)
    house = float(live_power["house"])
    baseload = round(max(0.0, house - flex_sum), 3)
    return {
        "house_kw": round(house, 3),
        "baseload_kw": baseload,
        "flex_kw": flex_kw,
        "flex_sum_kw": flex_sum,
        "pv_kw": float(live_power["pv"]),
        "grid_kw": float(live_power["grid"]),
        "battery_kw": float(live_power["battery"]),
    }


def _ui_slot_datetime() -> datetime:
    """Aktueller Zeitpunkt für Live-UI (Filter-Inferenz im nativen Fenster)."""
    return datetime.now(tz=_UI_TIMEZONE)


def _filter_contexts_from_config_fallback() -> dict[str, dict]:
    """Minimale Fenster-Infos aus config_fallback, wenn run_state keine hat."""
    contexts: dict[str, dict] = {}
    for consumer in config.get_flexible_consumers():
        if not filter_schedule_enabled(consumer):
            continue
        fallback = (consumer.get("filter_schedule") or {}).get("config_fallback") or {}
        start = fallback.get("native_start_hour")
        duration = fallback.get("native_duration_hours")
        if start is None or duration is None:
            continue
        contexts[consumer["id"]] = {
            "native_start_hour": float(start),
            "native_duration_hours": float(duration),
            "source_label": "config_fallback",
        }
    return contexts


def filter_contexts_for_ui(main_state: dict[str, Any] | None) -> dict[str, dict] | None:
    """Filter-Fenster für Live-UI: run_state oder config_fallback."""
    if main_state:
        stored = main_state.get("filter_contexts")
        if stored:
            return stored
    fallback = _filter_contexts_from_config_fallback()
    return fallback or None


def fetch_live_flex_kw_for_ui(main_state: dict[str, Any] | None = None) -> dict[str, float]:
    """
    Flex-Leistungen für Sankey/Live-UI mit Filter-Inferenz (Fall B).

    Nutzt filter_contexts aus dem letzten Produktiv-Lauf oder config_fallback.
    """
    return loxone_client.resolve_flexible_consumers_live_power(
        filter_contexts=filter_contexts_for_ui(main_state),
        slot_datetime=_ui_slot_datetime(),
    ).kw


def fetch_live_consumption_snapshot(
    main_state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Aktueller Verbrauchs-Snapshot: Haus gesamt, Grundlast, Flex je id, PV/Netz/Batterie.
    """
    live_power = loxone_client.fetch_loxone_live_power()
    if live_power is None:
        return None
    flex_kw = fetch_live_flex_kw_for_ui(main_state)
    return build_consumption_snapshot(live_power, flex_kw)


def apply_live_snapshot_to_matrix(
    matrix: list,
    snapshot: dict[str, Any],
    hour_index: int = 0,
) -> list:
    """Ersetzt die aktuelle Stunde in der Optimierungsmatrix durch Live-Messwerte."""
    if not matrix or not snapshot:
        return matrix
    if hour_index < 0 or hour_index >= len(matrix):
        return matrix

    updated = copy.deepcopy(matrix)
    row = updated[hour_index]
    row["expected_p_act"] = snapshot["baseload_kw"]
    row["expected_p_total"] = snapshot["house_kw"]
    row["expected_flex_kw"] = dict(snapshot["flex_kw"])
    row["expected_p_pv"] = snapshot["pv_kw"]
    row["consumption_mode"] = "live_snapshot"
    return updated
