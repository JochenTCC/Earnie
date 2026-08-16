"""Shared helpers for SE calculation test matrix (2.3)."""
from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / "earnie_env"
WORK_ROOT = DEFAULT_ENV / "runtime" / "se_calc_test"
CELLS_DIR = WORK_ROOT / "cells"
RUNS_DIR = WORK_ROOT / "runs"
DESCRIPTORS_PATH = WORK_ROOT / "matrix_descriptors.json"
RESULTS_JSON = ROOT / "docs" / "spec" / "se-calc-test-results.json"
RESULTS_MD_ANCHOR = ROOT / "docs" / "spec" / "se-calculation-test-plan.md"

SEASONAL_MONTHS = (1, 4, 7, 10)
DEFAULT_YEAR = 2025
PROFILE_ID = "example_efh"
LIVE_SCENARIO_ID = "live"
M2_CSV_CONSUMER_IDS = ("wp_heating", "ev", "swimspa")
PRIORITIZED_CELLS = ("M0", "M1", "M2")
ALL_CELL_IDS = ("M0", "M1", "M2", "M3", "M4")


def project_root() -> Path:
    return ROOT


def env_root(path: Path | None = None) -> Path:
    return Path(path) if path is not None else DEFAULT_ENV


def config_dir(env: Path | None = None) -> Path:
    return env_root(env) / "config"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    root_abs = os.path.abspath(str(ROOT))
    target_abs = os.path.abspath(str(path))
    prefix = root_abs if root_abs.endswith(os.sep) else root_abs + os.sep
    if target_abs != root_abs and not target_abs.startswith(prefix):
        raise ValueError(f"Refusing to write outside project root: {path}")
    target = Path(target_abs)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_house_profiles_doc(env: Path | None = None) -> dict:
    return load_json(config_dir(env) / "house_profiles.json")


def find_profile(doc: dict, profile_id: str = PROFILE_ID) -> dict:
    profiles = doc.get("profiles") or []
    if isinstance(profiles, list):
        for item in profiles:
            if isinstance(item, dict) and item.get("id") == profile_id:
                return item
    if isinstance(profiles, dict) and profile_id in profiles:
        return profiles[profile_id]
    raise KeyError(f"House profile '{profile_id}' not found")


def live_scenario_id(env: Path | None = None) -> str:
    cfg = load_json(config_dir(env) / "config.json")
    return str(cfg.get("live_scenario_id") or LIVE_SCENARIO_ID)


def inventory_snapshot(env: Path | None = None) -> dict:
    from house_config.profile_csv_policy import (
        controllable_generics,
        se_uses_meter_residual_baseload,
    )

    doc = load_house_profiles_doc(env)
    profile = find_profile(doc)
    consumers = []
    for raw in profile.get("consumers") or []:
        if not isinstance(raw, dict):
            continue
        consumers.append(
            {
                "id": raw.get("id"),
                "type": raw.get("type"),
                "earnie_role": raw.get("earnie_role"),
                "has_profile_csv": bool(raw.get("profile_csv")),
                "use_profile_csv": bool(raw.get("use_profile_csv")),
            }
        )
    controllables = [
        {
            "id": c.get("id"),
            "earnie_role": c.get("earnie_role"),
            "has_profile_csv": bool(c.get("profile_csv")),
            "use_profile_csv": bool(c.get("use_profile_csv")),
        }
        for c in controllable_generics(profile)
    ]
    return {
        "env": str(env_root(env)),
        "live_scenario_id": live_scenario_id(env),
        "house_profile_id": profile.get("id"),
        "baseload_kwh": profile.get("baseload_kwh"),
        "total_profile_csv": profile.get("total_profile_csv"),
        "historical_csv_source": profile.get("historical_csv_source"),
        "b_gate": bool(se_uses_meter_residual_baseload(profile)),
        "controllables": controllables,
        "consumers": consumers,
    }


def _set_all_use_profile_csv(profile: dict, enabled: bool) -> None:
    for consumer in profile.get("consumers") or []:
        if isinstance(consumer, dict):
            consumer["use_profile_csv"] = bool(enabled)


def _enable_csv_ids(profile: dict, ids: tuple[str, ...]) -> list[str]:
    enabled: list[str] = []
    wanted = set(ids)
    for consumer in profile.get("consumers") or []:
        if not isinstance(consumer, dict):
            continue
        cid = consumer.get("id")
        if cid not in wanted:
            continue
        if not consumer.get("profile_csv"):
            continue
        consumer["use_profile_csv"] = True
        enabled.append(str(cid))
    return enabled


def _known_with_csv_ids(profile: dict) -> list[str]:
    from house_config.earnie_role import is_earnie_known

    ids: list[str] = []
    for consumer in profile.get("consumers") or []:
        if not isinstance(consumer, dict):
            continue
        if consumer.get("type") != "generic":
            continue
        if not is_earnie_known(consumer):
            continue
        if consumer.get("profile_csv"):
            ids.append(str(consumer.get("id")))
    return ids


def apply_cell_to_profile(profile: dict, cell_id: str) -> dict:
    """Mutate a deep-copied profile for the matrix cell. Returns metadata."""
    meta: dict[str, Any] = {
        "cell": cell_id,
        "expected_baseload_path": "A",
        "skipped": False,
        "skip_reason": None,
        "enabled_csv_ids": [],
        "total_profile_csv": profile.get("total_profile_csv"),
    }
    _set_all_use_profile_csv(profile, False)

    if cell_id == "M0":
        return meta
    if cell_id == "M1":
        profile["total_profile_csv"] = ""
        meta["total_profile_csv"] = ""
        return meta
    if cell_id in ("M2", "M4"):
        meta["enabled_csv_ids"] = _enable_csv_ids(profile, M2_CSV_CONSUMER_IDS)
        return meta
    if cell_id == "M3":
        known_ids = _known_with_csv_ids(profile)
        if not known_ids:
            meta["skipped"] = True
            meta["skip_reason"] = "no known generics with profile_csv on baseline"
            return meta
        meta["enabled_csv_ids"] = _enable_csv_ids(profile, tuple(known_ids))
        return meta
    raise ValueError(f"Unknown matrix cell '{cell_id}'")


def live_only_scenarios_doc(env: Path | None = None) -> dict:
    doc = load_json(config_dir(env) / "backtesting_scenarios.json")
    live_id = live_scenario_id(env)
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("backtesting_scenarios.json needs scenarios array")
    kept = [s for s in scenarios if isinstance(s, dict) and s.get("id") == live_id]
    if not kept:
        raise ValueError(f"Live scenario '{live_id}' missing in scenarios")
    out = deepcopy(doc)
    out["scenarios"] = kept
    return out


def materialize_cell(cell_id: str, env: Path | None = None) -> dict:
    from house_config.profile_csv_policy import se_uses_meter_residual_baseload

    if cell_id not in ALL_CELL_IDS:
        raise ValueError(f"Unknown matrix cell '{cell_id}'")
    cell_id = next(cid for cid in ALL_CELL_IDS if cid == cell_id)

    base_env = env_root(env)
    profiles_doc = load_house_profiles_doc(base_env)
    profile = find_profile(profiles_doc)
    working = deepcopy(profile)
    meta = apply_cell_to_profile(working, cell_id)
    if meta.get("skipped"):
        return meta

    profiles = profiles_doc.get("profiles")
    if isinstance(profiles, list):
        profiles_doc["profiles"] = [
            working if (isinstance(p, dict) and p.get("id") == PROFILE_ID) else p
            for p in profiles
        ]
    elif isinstance(profiles, dict):
        profiles_doc["profiles"][PROFILE_ID] = working

    cell_dir = CELLS_DIR / cell_id
    if cell_dir.exists():
        shutil.rmtree(cell_dir)
    cell_dir.mkdir(parents=True, exist_ok=True)
    write_json(cell_dir / "house_profiles.json", profiles_doc)
    write_json(cell_dir / "backtesting_scenarios.json", live_only_scenarios_doc(base_env))

    b_gate = bool(se_uses_meter_residual_baseload(working))
    meta.update(
        {
            "cell_dir": str(cell_dir),
            "house_profiles_path": str(cell_dir / "house_profiles.json"),
            "scenarios_path": str(cell_dir / "backtesting_scenarios.json"),
            "b_gate": b_gate,
            "env_root": str(base_env),
        }
    )
    if b_gate:
        meta["hard_fail_hint"] = "B-gate unexpectedly True for path-A matrix cell"
    return meta


def materialize_cells(cell_ids: list[str], env: Path | None = None) -> dict:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    inventory = inventory_snapshot(env)
    cells: dict[str, dict] = {}
    for cell_id in cell_ids:
        cells[cell_id] = materialize_cell(cell_id, env)
    payload = {
        "inventory": inventory,
        "cells": cells,
        "year": DEFAULT_YEAR,
        "months": list(SEASONAL_MONTHS),
    }
    write_json(DESCRIPTORS_PATH, payload)
    return payload


def run_output_dir(cell_id: str, year: int, month: int) -> Path:
    return RUNS_DIR / cell_id / f"{year:04d}-{month:02d}"


def parse_csv_ids(raw: str | None, default: tuple[str, ...]) -> list[str]:
    if not raw or not str(raw).strip():
        return list(default)
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def parse_months(raw: str | None) -> list[int]:
    if not raw or not str(raw).strip():
        return list(SEASONAL_MONTHS)
    months: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        month = int(part)
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid month {month}")
        months.append(month)
    return months
