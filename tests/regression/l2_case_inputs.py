"""Per-case overrides of the L2 backtesting fixture (``case.yaml`` ``inputs:``), fail loud.

A case changes the fixture only through the keys below. Scenario and house profile changes are
written as patched copies of the fixture files into the run's work directory, so the normal
scenario resolution reads and validates them (no second resolution path for regression cases).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_SCENARIO_ID = "fixture_5kwh_fixed"

INPUT_KEYS = frozenset({
    "kind",
    "scenario_id",
    "initial_soc",
    "import_tariff",
    "grid_fee_base_cent_kwh",
    "grid_capacity_charges",
    "force_negative_price",
    "scenario_settings",
    "house_profile_patch",
    "heating_system_patch",
})

# Settings a case may add to its scenario on top of the ones the scenario already has.
EXTRA_SCENARIO_SETTINGS = frozenset({
    "house_profile_id",
    "import_cap_kw",
    "import_cap_margin_kw",
})

EXTRA_METRIC_KEYS = frozenset({"consumer_kwh", "consumer_price_ct"})

SCENARIOS_ENV = "EARNIE_BACKTESTING_SCENARIOS_PATH"
HOUSE_PROFILES_ENV = "EARNIE_HOUSE_PROFILES_PATH"
COMPONENTS_ENV = "EARNIE_COMPONENTS_PATH"


def case_inputs(meta: dict[str, Any], case_id: str) -> dict[str, Any]:
    """The ``inputs:`` block; unknown keys raise."""
    inputs = dict(meta.get("inputs") or {})
    unknown = sorted(set(inputs) - INPUT_KEYS)
    if unknown:
        raise ValueError(
            f"case {case_id}: unknown inputs keys {unknown}; allowed: {sorted(INPUT_KEYS)}"
        )
    if inputs.get("grid_capacity_charges") is not None:
        if inputs.get("grid_fee_base_cent_kwh") is None:
            raise ValueError(
                f"case {case_id}: grid_capacity_charges needs grid_fee_base_cent_kwh "
                "(the charges belong to the case grid area)"
            )
        if not isinstance(inputs["grid_capacity_charges"], list):
            raise TypeError(f"case {case_id}: grid_capacity_charges must be a list")
    return inputs


def scenario_id(inputs: dict[str, Any]) -> str:
    return str(inputs.get("scenario_id") or DEFAULT_SCENARIO_ID)


def consumer_metric_ids(
    meta: dict[str, Any], case_id: str, key: str = "consumer_kwh"
) -> tuple[str, ...]:
    """Consumer IDs listed under ``extra_metrics.<key>``: ``consumer_kwh`` (energy) or
    ``consumer_price_ct`` (energy-weighted import price)."""
    if key not in EXTRA_METRIC_KEYS:
        raise ValueError(f"unknown extra_metrics key {key!r}")
    extra = meta.get("extra_metrics")
    if extra is None:
        return ()
    if not isinstance(extra, dict):
        raise TypeError(f"case {case_id}: extra_metrics must be a mapping")
    unknown = sorted(set(extra) - EXTRA_METRIC_KEYS)
    if unknown:
        raise ValueError(
            f"case {case_id}: unknown extra_metrics keys {unknown}; "
            f"allowed: {sorted(EXTRA_METRIC_KEYS)}"
        )
    ids = extra.get(key) or []
    if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
        raise TypeError(f"case {case_id}: extra_metrics.{key} must be a list of IDs")
    return tuple(ids)


def write_case_config(
    inputs: dict[str, Any], work_dir: Path, *, fixtures_root: Path, case_id: str
) -> dict[str, Path]:
    """Patched fixture files for ``scenario_settings`` / ``house_profile_patch`` /
    ``heating_system_patch``.

    Returns env var → path of each file written; empty without overrides.
    """
    paths: dict[str, Path] = {}
    system_patch = inputs.get("heating_system_patch")
    if system_patch is not None:
        paths[COMPONENTS_ENV] = _write_heating_system_patch(
            system_patch, work_dir, fixtures_root=fixtures_root, case_id=case_id
        )
    settings_patch = inputs.get("scenario_settings")
    profile_patch = inputs.get("house_profile_patch")
    if settings_patch is None and profile_patch is None:
        return paths
    sid = scenario_id(inputs)
    scenarios_doc = _read_json(fixtures_root / "backtesting_scenarios.json")
    entry = _scenario_entry(scenarios_doc, sid, case_id)
    settings = entry.setdefault("settings", {})
    if settings_patch is not None:
        if not isinstance(settings_patch, dict):
            raise TypeError(f"case {case_id}: scenario_settings must be a mapping")
        allowed = EXTRA_SCENARIO_SETTINGS | set(settings)
        unknown = sorted(set(settings_patch) - allowed)
        if unknown:
            raise ValueError(
                f"case {case_id}: scenario_settings keys {unknown} are neither settings of "
                f"scenario {sid!r} nor in {sorted(EXTRA_SCENARIO_SETTINGS)}"
            )
        settings.update(settings_patch)
        path = work_dir / "backtesting_scenarios.json"
        _write_json(path, scenarios_doc)
        paths[SCENARIOS_ENV] = path
    if profile_patch is not None:
        if not isinstance(profile_patch, dict):
            raise TypeError(f"case {case_id}: house_profile_patch must be a mapping")
        profile_id = str(settings.get("house_profile_id") or "").strip()
        if not profile_id:
            raise ValueError(
                f"case {case_id}: house_profile_patch needs a house_profile_id on scenario "
                f"{sid!r} (set it in scenario_settings)"
            )
        profiles_doc = _read_json(fixtures_root / "house_profiles.json")
        profiles = profiles_doc.get("profiles") or []
        index = next(
            (i for i, p in enumerate(profiles) if isinstance(p, dict) and p.get("id") == profile_id),
            None,
        )
        if index is None:
            raise ValueError(f"case {case_id}: house profile {profile_id!r} not in the fixture")
        profiles[index] = deep_merge(profiles[index], profile_patch)
        path = work_dir / "house_profiles.json"
        _write_json(path, profiles_doc)
        paths[HOUSE_PROFILES_ENV] = path
    return paths


def _write_heating_system_patch(
    system_patch: Any, work_dir: Path, *, fixtures_root: Path, case_id: str
) -> Path:
    """``components.json`` with heating systems patched by id (``{system id: patch}``)."""
    if not isinstance(system_patch, dict) or not system_patch:
        raise TypeError(f"case {case_id}: heating_system_patch must be a non-empty mapping")
    doc = _read_json(fixtures_root / "components.json")
    systems = doc.get("heating_systems") or []
    for system_id, patch in system_patch.items():
        if not isinstance(patch, dict):
            raise TypeError(f"case {case_id}: heating_system_patch.{system_id} must be a mapping")
        index = next(
            (i for i, s in enumerate(systems) if isinstance(s, dict) and s.get("id") == system_id),
            None,
        )
        if index is None:
            raise ValueError(f"case {case_id}: heating system {system_id!r} not in the fixture")
        systems[index] = deep_merge(systems[index], patch)
    path = work_dir / "components.json"
    _write_json(path, doc)
    return path


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """``patch`` over ``base``: mappings merge key by key, every other value replaces."""
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _scenario_entry(doc: dict[str, Any], sid: str, case_id: str) -> dict[str, Any]:
    for entry in doc.get("scenarios") or []:
        if isinstance(entry, dict) and entry.get("id") == sid:
            return entry
    raise ValueError(f"case {case_id}: scenario {sid!r} not in the fixture")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
