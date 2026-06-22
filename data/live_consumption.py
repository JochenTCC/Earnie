"""
live_consumption.py – Read-only Live-Snapshot aus Loxone für app.py (Sankey, What-if).

Schreibt keine cons_data; nur Lesen über loxone_client.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from integrations import loxone_client

logger = logging.getLogger(__name__)


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


def fetch_live_consumption_snapshot() -> dict[str, Any] | None:
    """
    Aktueller Verbrauchs-Snapshot: Haus gesamt, Grundlast, Flex je id, PV/Netz/Batterie.
    """
    live_power = loxone_client.fetch_loxone_live_power()
    if live_power is None:
        return None
    flex_kw = loxone_client.fetch_flexible_consumers_live_kw()
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
