"""
live_optimization_debug.py – Persistierter Debug-Snapshot der App-24h-Simulation.

Nur app.py schreibt; manuelle Analyse kann die JSON-Datei lesen.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from .file_metadata import (
    LIVE_OPTIMIZATION_DEBUG_SCHEMA,
    stamp_payload,
    strip_metadata,
)

logger = logging.getLogger(__name__)

from runtime_store.env_vars import read_env_or

RUNTIME_DIR = read_env_or("RUNTIME_DIR", "runtime")
DEBUG_FILES = {
    "live": os.path.join(RUNTIME_DIR, "live_optimization_debug.json"),
    "historical_day": os.path.join(RUNTIME_DIR, "historical_optimization_debug.json"),
}
LEGACY_DEBUG_PATH = "live_optimization_debug.json"

_MAIN_RUN_KEYS = (
    "completed_at",
    "source",
    "success",
    "soc_percent",
    "mode",
    "target_power_kw",
    "target_soc_percent",
    "battery_plan_kw",
    "consumer_powers_kw",
    "flex_live_kw",
    "consumption_snapshot",
    "forecast_pv_kw",
    "forecast_consumption_kw",
    "current_hour",
)


def _candidate_paths(kind: str) -> list[str]:
    primary = DEBUG_FILES.get(kind, DEBUG_FILES["live"])
    if kind == "live":
        return [primary, LEGACY_DEBUG_PATH]
    return [primary]


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_json(path: str, data: dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _save_to_path(path: str, data: dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    tmp = f"{path}.tmp"
    try:
        _write_json(tmp, data)
        os.replace(tmp, path)
    except OSError as e:
        if getattr(e, "errno", None) != 16:
            raise
        logger.warning(
            "live_optimization_debug: atomares Schreiben nach %s nicht möglich (%s), direkter Versuch",
            path,
            e,
        )
        _write_json(path, data)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _main_run_summary(main_state: dict[str, Any] | None) -> dict[str, Any]:
    if not main_state:
        return {}
    clean = strip_metadata(main_state)
    return {key: clean[key] for key in _MAIN_RUN_KEYS if key in clean}


def _savings_summary(savings_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline_cost_euro": savings_info.get("baseline_cost_euro"),
        "matched_baseline_cost_euro": savings_info.get("matched_baseline_cost_euro"),
        "optimized_cost_euro": savings_info.get("optimized_cost_euro"),
        "savings_euro": savings_info.get("savings_euro"),
        "savings_matched_euro": savings_info.get("savings_matched_euro"),
        "baseline_consumption_kwh": savings_info.get("baseline_consumption_kwh"),
        "matched_baseline_consumption_kwh": savings_info.get(
            "matched_baseline_consumption_kwh"
        ),
        "optimized_consumption_kwh": savings_info.get("optimized_consumption_kwh"),
        "baseload_kwh": savings_info.get("baseload_kwh"),
    }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _json_safe(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(item) for item in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def build_debug_payload(
    savings_info: dict[str, Any],
    optimized_rows: list[dict],
    baseline_rows: list[dict],
    *,
    kind: str,
    initial_soc: float,
    main_state: dict[str, Any] | None = None,
    quarter_hour_slot: str | None = None,
    sync_reason: str | None = None,
    optimized_rows_raw: list[dict] | None = None,
    target_date: str | None = None,
    historical_meta: dict[str, Any] | None = None,
    matched_baseline_rows: list[dict] | None = None,
) -> dict[str, Any]:
    """Gemeinsamer Snapshot für Debug und Nachrechnen."""
    main_summary = _main_run_summary(main_state)
    payload: dict[str, Any] = {
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "source": "app.py",
        "simulation_kind": kind,
        "initial_soc_percent": round(float(initial_soc), 2),
        "savings": _savings_summary(savings_info),
        "applied_targets": savings_info.get("applied_targets") or [],
        "energy_comparison": savings_info.get("energy_comparison") or [],
        "simulation_rows": optimized_rows,
        "baseline_rows": baseline_rows,
        "matched_baseline_rows": matched_baseline_rows or [],
    }
    if kind == "live":
        payload["quarter_hour_slot"] = quarter_hour_slot
        payload["sync_reason"] = sync_reason
        payload["simulation_rows_raw"] = optimized_rows_raw or optimized_rows
        payload["main_run"] = main_summary
        payload["main_run_completed_at"] = main_summary.get("completed_at")
    else:
        payload["target_date"] = target_date
        payload["historical_meta"] = historical_meta or {}
    return _json_safe(payload)


def save_debug_snapshot(
    payload: dict[str, Any],
    *,
    kind: str = "live",
    path: str | None = None,
) -> None:
    """Schreibt den letzten Debug-Snapshot (runtime-Verzeichnis mit Fallback)."""
    data = stamp_payload(payload, schema_version=LIVE_OPTIMIZATION_DEBUG_SCHEMA)
    targets = [path] if path else _candidate_paths(kind)
    errors: list[str] = []
    for target in targets:
        try:
            _save_to_path(target, data)
            return
        except OSError as e:
            errors.append(f"{target}: {e}")
    raise OSError("; ".join(errors))
