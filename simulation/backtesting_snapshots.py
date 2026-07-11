"""Persistenz und Laden von Fenster-Snapshots für Backtesting-Chart1/2 (1.25.f)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import pandas as pd

from runtime_store.file_metadata import stamp_payload
from runtime_store.live_optimization_debug import _json_safe
from simulation.backtesting_horizon import geo_params_from_scenario
from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW

BACKTESTING_WINDOW_SNAPSHOTS_JSONL = "backtesting_window_snapshots.jsonl"
WINDOW_SNAPSHOT_SCHEMA = 1


def normalize_window_anchor_key(value: str | datetime) -> str:
    """Einheitlicher Lookup-Schlüssel für window_anchor."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.isoformat()


def _serialize_meta(meta: dict) -> dict:
    payload = dict(meta)
    flexible = payload.pop("_flexible_consumers", None)
    serialized = _json_safe(payload)
    if flexible is not None:
        serialized["_flexible_consumers"] = _json_safe(flexible)
    return serialized


def build_window_snapshot(
    *,
    window_anchor: datetime,
    scenario_id: str,
    horizon_mode: str,
    kind: str,
    initial_soc: float,
    meta: dict,
    chart_rows_24h: list[dict],
    matrix_24h: list[dict],
    chart_rows_full: list[dict] | None = None,
    matrix_full: list[dict] | None = None,
    sunrise_soc_min_index: int | None = None,
    scenario_params: dict | None = None,
    battery_params: dict | None = None,
) -> dict:
    """Baut ein serialisierbares Fenster-Snapshot-Dict."""
    geo: dict[str, Any] | None = None
    if scenario_params and horizon_mode == SUNRISE_WINDOW:
        lat, lon, tz_name = geo_params_from_scenario(scenario_params)
        geo = {"latitude": lat, "longitude": lon, "timezone": tz_name}

    payload: dict[str, Any] = {
        "window_anchor": normalize_window_anchor_key(window_anchor),
        "scenario_id": scenario_id,
        "horizon_mode": horizon_mode,
        "kind": kind,
        "initial_soc": round(float(initial_soc), 2),
        "meta": _serialize_meta(meta),
        "matrix_24h": _json_safe(matrix_24h),
        "chart_rows_24h": _json_safe(chart_rows_24h),
    }
    if sunrise_soc_min_index is not None:
        payload["sunrise_soc_min_index"] = sunrise_soc_min_index
    if geo is not None:
        payload["geo"] = geo
    if chart_rows_full is not None and matrix_full is not None:
        payload["chart_rows_full"] = _json_safe(chart_rows_full)
        payload["matrix_full"] = _json_safe(matrix_full)
    if battery_params is not None:
        payload["battery_params"] = _json_safe(battery_params)

    return stamp_payload(payload, schema_version=WINDOW_SNAPSHOT_SCHEMA)


def write_window_snapshots_jsonl(
    log_dir: str,
    snapshots: list[dict],
) -> str | None:
    """Schreibt alle Snapshots in eine JSONL-Datei (überschreibt bestehende)."""
    if not snapshots:
        return None
    path = os.path.join(log_dir, BACKTESTING_WINDOW_SNAPSHOTS_JSONL)
    with open(path, "w", encoding="utf-8") as handle:
        for snapshot in snapshots:
            handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return path


def remove_window_snapshots_jsonl(log_dir: str) -> None:
    """Entfernt veraltete Fenster-Snapshots (z. B. nach Lauf ohne kritische Fälle)."""
    path = os.path.join(log_dir, BACKTESTING_WINDOW_SNAPSHOTS_JSONL)
    if os.path.isfile(path):
        os.remove(path)


def load_all_window_snapshots(log_dir: str) -> list[dict]:
    path = os.path.join(log_dir, BACKTESTING_WINDOW_SNAPSHOTS_JSONL)
    if not os.path.isfile(path):
        return []
    snapshots: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            snapshots.append(json.loads(line))
    return snapshots


def load_window_snapshot(
    log_dir: str,
    window_anchor: str,
    scenario_id: str,
) -> dict | None:
    """Lädt einen Snapshot für Fenster + Szenario."""
    anchor_key = normalize_window_anchor_key(window_anchor)
    for snapshot in load_all_window_snapshots(log_dir):
        if snapshot.get("scenario_id") != scenario_id:
            continue
        if normalize_window_anchor_key(snapshot.get("window_anchor", "")) == anchor_key:
            return snapshot
    return None


def snapshot_supports_sunrise_view(snapshot: dict) -> bool:
    return (
        snapshot.get("horizon_mode") == SUNRISE_WINDOW
        and bool(snapshot.get("chart_rows_full"))
        and bool(snapshot.get("matrix_full"))
    )
