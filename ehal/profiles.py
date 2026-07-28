"""Load and validate device-role, hardware-profile, and Loxone recipe templates (2.4.g).

No network I/O. Does not change Live wire schemas (telemetry/setpoint/capabilities).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from ehal.validate import EhalValidationError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROLES_DIR = _REPO_ROOT / "share" / "ehal" / "roles"
_ROLES_SCHEMA = _REPO_ROOT / "share" / "ehal" / "device_roles.schema.json"
_HW_DIR = _REPO_ROOT / "share" / "hardware_profiles"
_HW_SCHEMA = _HW_DIR / "hardware_profile.schema.json"
_HW_EXAMPLES = _HW_DIR / "examples"
_RECIPES_DIR = _REPO_ROOT / "share" / "loxone" / "recipes"
_RECIPE_SCHEMA = _RECIPES_DIR / "recipe.schema.json"

# M1 EHAL field surface (telemetry + setpoint + capabilities).
M1_EHAL_FIELDS: frozenset[str] = frozenset(
    {
        "grid_power_active",
        "pv_production_active",
        "ess_soc",
        "ess_power",
        "evcs_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
        "set_evcs_max_current",
        "supports_ess_write",
        "supports_evcs_current",
    }
)

# HITL display labels (German) for M1 mapping fields — single source for UI.
_FIELD_LABELS_DE: dict[str, str] = {
    "grid_power_active": "Netzleistung (W, +Bezug)",
    "pv_production_active": "PV-Produktion (W)",
    "ess_soc": "Batterie-SoC (%)",
    "ess_power": "Batterieleistung (W, +Entladung)",
    "evcs_active_power": "Wallbox-Leistung (W)",
    "set_ess_charge_power_limit": "Setpoint Ladegrenze (W)",
    "set_ess_discharge_power_limit": "Setpoint Entladegrenze (W)",
    "set_evcs_max_current": "Setpoint Wallbox-Maxstrom (A)",
    "target_soc_name": "Loxone-Extras: Ziel-SOC",
    "control_cmd_name": "Loxone-Extras: Steuerbefehl",
}

# Field → device role_id for HITL grouping (M1 plant roles only).
_FIELD_ROLE: dict[str, str] = {
    "grid_power_active": "grid",
    "pv_production_active": "pv",
    "ess_soc": "ess",
    "ess_power": "ess",
    "set_ess_charge_power_limit": "ess",
    "set_ess_discharge_power_limit": "ess",
    "evcs_active_power": "evcs",
    "set_evcs_max_current": "evcs",
}

_ROLE_ORDER = ("grid", "pv", "ess", "evcs", "consumer", "heatpump")


def roles_dir() -> Path:
    return _ROLES_DIR


def hardware_profiles_dir() -> Path:
    return _HW_DIR


def recipes_dir() -> Path:
    return _RECIPES_DIR


@lru_cache(maxsize=8)
def _load_schema(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise ValueError(f"Schema must be an object: {path}")
    return doc


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise EhalValidationError(f"Profile document must be an object: {path}")
    return doc


def _validate_against(schema_path: Path, document: dict[str, Any], kind: str) -> dict[str, Any]:
    schema = _load_schema(str(schema_path))
    try:
        jsonschema.validate(instance=document, schema=schema)
    except jsonschema.ValidationError as exc:
        raise EhalValidationError(
            f"{kind} failed schema validation: {exc.message}"
        ) from exc
    return document


def list_device_roles() -> list[str]:
    """Return role_id values for JSON files in share/ehal/roles/."""
    if not _ROLES_DIR.is_dir():
        return []
    ids = sorted(p.stem for p in _ROLES_DIR.glob("*.json"))
    return [rid for rid in _ROLE_ORDER if rid in ids] + [
        rid for rid in ids if rid not in _ROLE_ORDER
    ]


def load_device_role(role_id: str) -> dict[str, Any]:
    """Load and validate one device-role template."""
    path = _ROLES_DIR / f"{role_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Device role not found: {path}")
    doc = _validate_against(_ROLES_SCHEMA, _read_json(path), f"device role {role_id!r}")
    if doc.get("role_id") != role_id:
        raise EhalValidationError(
            f"Device role file {path.name} has role_id={doc.get('role_id')!r}, expected {role_id!r}"
        )
    return doc


def list_hardware_profiles() -> list[str]:
    """Return stem names of outline/example JSON under share/hardware_profiles/examples/."""
    if not _HW_EXAMPLES.is_dir():
        return []
    return sorted(p.stem for p in _HW_EXAMPLES.glob("*.json"))


def load_hardware_profile(stem: str) -> dict[str, Any]:
    """Load and validate one hardware-profile outline by file stem."""
    path = _HW_EXAMPLES / f"{stem}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Hardware profile not found: {path}")
    return _validate_against(
        _HW_SCHEMA, _read_json(path), f"hardware profile {stem!r}"
    )


def list_loxone_recipes() -> list[str]:
    """Return role_id values for Loxone recipe JSON (excludes recipe.schema.json)."""
    if not _RECIPES_DIR.is_dir():
        return []
    ids = sorted(
        p.stem
        for p in _RECIPES_DIR.glob("*.json")
        if p.name != "recipe.schema.json"
    )
    return [rid for rid in _ROLE_ORDER if rid in ids] + [
        rid for rid in ids if rid not in _ROLE_ORDER
    ]


def load_loxone_recipe(role_id: str) -> dict[str, Any]:
    """Load and validate one Loxone Merker recipe."""
    path = _RECIPES_DIR / f"{role_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Loxone recipe not found: {path}")
    doc = _validate_against(_RECIPE_SCHEMA, _read_json(path), f"loxone recipe {role_id!r}")
    if doc.get("role_id") != role_id:
        raise EhalValidationError(
            f"Loxone recipe file {path.name} has role_id={doc.get('role_id')!r}, expected {role_id!r}"
        )
    return doc


def role_field_labels() -> dict[str, str]:
    """German HITL labels for EHAL mapping fields (and Loxone extras)."""
    return dict(_FIELD_LABELS_DE)


def field_role_id(field: str) -> str | None:
    """Return device role_id for an M1 mapping field, or None."""
    return _FIELD_ROLE.get(field)


def role_group_label(role_id: str) -> str:
    """Short German section caption for HITL grouping."""
    try:
        return str(load_device_role(role_id).get("label") or role_id)
    except (OSError, EhalValidationError, FileNotFoundError):
        return role_id


def m1_fields_for_role(role_id: str) -> list[str]:
    """M1 EHAL field names listed on a role template (excludes kind=stub)."""
    role = load_device_role(role_id)
    out: list[str] = []
    for item in role.get("ehal_fields") or []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "stub":
            continue
        field = str(item.get("field") or "")
        if field in M1_EHAL_FIELDS:
            out.append(field)
    return out


def group_fields_by_role(fields: tuple[str, ...] | list[str]) -> list[tuple[str, list[str]]]:
    """Order fields into (role_id, fields) groups for HITL sections.

    Unknown fields are collected under role_id ``other``.
    """
    buckets: dict[str, list[str]] = {rid: [] for rid in ("grid", "pv", "ess", "evcs")}
    other: list[str] = []
    for field in fields:
        role = _FIELD_ROLE.get(field)
        if role and role in buckets:
            buckets[role].append(field)
        else:
            other.append(field)
    groups: list[tuple[str, list[str]]] = []
    for role_id in ("grid", "pv", "ess", "evcs"):
        if buckets[role_id]:
            groups.append((role_id, buckets[role_id]))
    if other:
        groups.append(("other", other))
    return groups
