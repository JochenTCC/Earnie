"""
live_optimization_debug.py – Persistierter Debug-Snapshot der App-24h-Simulation.

Nur app.py schreibt; App, main.py und manuelle Analyse können lesen.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import config
from optimizer import steuerbefehl_for_mode
from .file_metadata import (
    LIVE_OPTIMIZATION_DEBUG_SCHEMA,
    read_schema_version,
    stamp_payload,
    strip_metadata,
)

logger = logging.getLogger(__name__)

RUNTIME_DIR = os.environ.get("ENERGY_OPTIMIZER_RUNTIME_DIR", "runtime")
DEBUG_FILES = {
    "live": os.path.join(RUNTIME_DIR, "live_optimization_debug.json"),
    "historical_day": os.path.join(RUNTIME_DIR, "historical_optimization_debug.json"),
}
LEGACY_DEBUG_PATH = "live_optimization_debug.json"

KW_TOLERANCE = 0.02

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


def debug_file_path(kind: str = "live") -> str:
    return DEBUG_FILES.get(kind, DEBUG_FILES["live"])


def _candidate_paths(kind: str) -> list[str]:
    primary = debug_file_path(kind)
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


def _load_from_path(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        schema_version = read_schema_version(data, default=1)
        if schema_version > LIVE_OPTIMIZATION_DEBUG_SCHEMA:
            logger.warning(
                "live_optimization_debug: neuere Schema-Version %s (aktuell %s)",
                schema_version,
                LIVE_OPTIMIZATION_DEBUG_SCHEMA,
            )
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("live_optimization_debug: Lesen von %s fehlgeschlagen: %s", path, e)
        return None


def _kw_match(a: float, b: float, tol: float = KW_TOLERANCE) -> bool:
    return abs(float(a) - float(b)) <= tol


def _hour0_row(rows: list[dict] | None) -> dict[str, Any]:
    if not rows:
        return {}
    return dict(rows[0])


def _main_run_summary(main_state: dict[str, Any] | None) -> dict[str, Any]:
    if not main_state:
        return {}
    clean = strip_metadata(main_state)
    return {key: clean[key] for key in _MAIN_RUN_KEYS if key in clean}


def _savings_summary(savings_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline_cost_euro": savings_info.get("baseline_cost_euro"),
        "optimized_cost_euro": savings_info.get("optimized_cost_euro"),
        "savings_euro": savings_info.get("savings_euro"),
        "baseline_consumption_kwh": savings_info.get("baseline_consumption_kwh"),
        "optimized_consumption_kwh": savings_info.get("optimized_consumption_kwh"),
        "baseload_kwh": savings_info.get("baseload_kwh"),
    }


def build_plausibility(
    main_state: dict[str, Any] | None,
    simulation_hour0: dict[str, Any] | None,
) -> dict[str, Any]:
    """Vergleicht Stunde 0 der Simulation mit dem Produktiv-Durchlauf von main.py."""
    if not main_state or not main_state.get("success"):
        return {"available": False, "aligned": False, "issues": ["Kein erfolgreicher main.py-Lauf."]}
    if not simulation_hour0:
        return {"available": False, "aligned": False, "issues": ["Keine Simulationszeile für Stunde 0."]}

    issues: list[str] = []
    checks: list[dict[str, Any]] = []

    mode = int(main_state.get("mode", 0))
    target_power = float(main_state.get("target_power_kw", 0.0) or 0.0)
    expected_cmd = steuerbefehl_for_mode(mode, target_power)
    sim_cmd = str(simulation_hour0.get("Steuerbefehl", ""))
    mode_ok = sim_cmd == expected_cmd
    checks.append({
        "field": "Steuerbefehl",
        "main": expected_cmd,
        "simulation": sim_cmd,
        "ok": mode_ok,
    })
    if not mode_ok:
        issues.append(f"Steuerbefehl: main.py={expected_cmd!r}, Simulation={sim_cmd!r}")

    if "battery_plan_kw" in main_state:
        main_batt = float(main_state["battery_plan_kw"])
        sim_batt = float(simulation_hour0.get("Geplante Batterie-Aktion (kW)", 0.0) or 0.0)
        batt_ok = _kw_match(main_batt, sim_batt)
        checks.append({
            "field": "Batterie (kW)",
            "main": round(main_batt, 3),
            "simulation": round(sim_batt, 3),
            "ok": batt_ok,
        })
        if not batt_ok:
            issues.append(
                f"Batterie: main.py={main_batt:.3f} kW, Simulation={sim_batt:.3f} kW"
            )

    flex_checks: list[dict[str, Any]] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = f"{consumer['name']} (kW)"
        cid = consumer["id"]
        main_kw = float((main_state.get("consumer_powers_kw") or {}).get(cid, 0.0) or 0.0)
        sim_kw = float(simulation_hour0.get(col, 0.0) or 0.0) if col in simulation_hour0 else 0.0
        flex_ok = _kw_match(main_kw, sim_kw)
        flex_checks.append({
            "id": cid,
            "name": consumer["name"],
            "main_kw": round(main_kw, 3),
            "simulation_kw": round(sim_kw, 3),
            "ok": flex_ok,
        })
        if not flex_ok:
            issues.append(
                f"{consumer['name']}: main.py={main_kw:.3f} kW, Simulation={sim_kw:.3f} kW"
            )

    return {
        "available": True,
        "aligned": len(issues) == 0,
        "checks": checks,
        "flex_consumers": flex_checks,
        "issues": issues,
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
) -> dict[str, Any]:
    """Gemeinsamer Snapshot für Debug und Nachrechnen."""
    main_summary = _main_run_summary(main_state)
    hour0 = _hour0_row(optimized_rows)
    hour0_raw = _hour0_row(optimized_rows_raw or optimized_rows)
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
    }
    if kind == "live":
        payload["quarter_hour_slot"] = quarter_hour_slot
        payload["sync_reason"] = sync_reason
        payload["simulation_rows_raw"] = optimized_rows_raw or optimized_rows
        payload["main_run"] = main_summary
        payload["main_run_completed_at"] = main_summary.get("completed_at")
        payload["plausibility_before_overlay"] = build_plausibility(main_state, hour0_raw)
        payload["plausibility"] = build_plausibility(main_state, hour0)
    else:
        payload["target_date"] = target_date
        payload["historical_meta"] = _json_safe(historical_meta or {})
    return payload


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


def load_debug_snapshot(kind: str = "live", path: str | None = None) -> dict[str, Any] | None:
    """Letzten Debug-Snapshot laden."""
    if path:
        return _load_from_path(path)
    for candidate in _candidate_paths(kind):
        state = _load_from_path(candidate)
        if state is not None:
            return state
    return None
