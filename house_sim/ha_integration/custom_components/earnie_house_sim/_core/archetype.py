# GENERATED — edit house_sim/core/ (or fixtures), then run:
#   python -m scripts.sync_house_sim_integration
# Do not hand-edit this copy.
"""Load hand-authored archetype fixtures (pure; no StateStore)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class StateWriter(Protocol):
    """Minimal store interface for projecting physics onto entity states."""

    def get(self, entity_id: str) -> dict[str, Any] | None: ...

    def set_state(self, entity_id: str, state: str) -> None: ...


@dataclass(frozen=True)
class ArchetypePackage:
    name: str
    root: Path
    entities: list[dict[str, Any]]
    ehal_entities: dict[str, str]
    ehal_sign: dict[str, str]
    house_params: dict[str, Any]
    pv_series_kw: list[float]
    devices: list[dict[str, Any]]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_archetype(name: str, *, fixtures_dir: Path | None = None) -> ArchetypePackage:
    root = (fixtures_dir or FIXTURES_DIR) / name
    if not root.is_dir():
        raise FileNotFoundError(f"Archetype fixture not found: {root}")

    entities_doc = _read_json(root / "entities.json")
    if isinstance(entities_doc, dict):
        entities = list(entities_doc.get("entities") or [])
        devices = list(entities_doc.get("devices") or [])
    elif isinstance(entities_doc, list):
        entities = list(entities_doc)
        devices = []
    else:
        raise ValueError(f"entities.json must be a list or {{entities: [...]}}: {root}")

    map_doc = _read_json(root / "ehal.ha.entities.json")
    if not isinstance(map_doc, dict):
        raise ValueError("ehal.ha.entities.json must be an object")
    ehal_entities = {
        str(k): str(v)
        for k, v in dict(map_doc.get("entities") or map_doc).items()
        if k != "sign" and str(v).strip()
    }
    sign_raw = map_doc.get("sign")
    ehal_sign = (
        {str(k): str(v) for k, v in dict(sign_raw).items()}
        if isinstance(sign_raw, dict)
        else {}
    )

    house_params = _read_json(root / "house_params.json")
    if not isinstance(house_params, dict):
        raise ValueError("house_params.json must be an object")

    pv_doc = _read_json(root / "pv_series.json")
    if isinstance(pv_doc, dict):
        series = list(pv_doc.get("kw") or pv_doc.get("pv_kw") or [])
    elif isinstance(pv_doc, list):
        series = list(pv_doc)
    else:
        raise ValueError("pv_series.json must be a list or {kw: [...]}")
    pv_series_kw = [float(x) for x in series]
    if not pv_series_kw:
        raise ValueError(f"pv_series.json is empty: {root}")

    return ArchetypePackage(
        name=name,
        root=root,
        entities=entities,
        ehal_entities=ehal_entities,
        ehal_sign=ehal_sign,
        house_params=house_params,
        pv_series_kw=pv_series_kw,
        devices=devices,
    )


def battery_energy_entity_id(package: ArchetypePackage, direction: str) -> str:
    """Sim-only battery kWh counter (``charge`` / ``discharge``); not an EHAL field."""
    raw = package.house_params.get("battery_energy_entities")
    if not isinstance(raw, dict):
        return ""
    return str(raw.get(direction) or "").strip()


# Physical quantity → {unit (lowercase) → factor to the base unit}.
# Base units: power W, energy kWh, percent %.
UNIT_FACTORS: dict[str, dict[str, float]] = {
    "power": {"w": 1.0, "kw": 1000.0, "mw": 1_000_000.0},
    "energy": {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0},
    "percent": {"%": 1.0},
}

# EHAL telemetry field → (physics key, quantity, factor physics value → base unit).
TELEMETRY_PROJECTION: dict[str, tuple[str, str, float]] = {
    "sens_pv_production_active": ("pv_kw", "power", 1000.0),
    "sens_ess_soc": ("soc_pct", "percent", 1.0),
    "sens_ess_power": ("ess_power_w", "power", 1.0),
    "sens_grid_power_active": ("grid_power_w", "power", 1.0),
    "sens_evcs_active_power": ("evcs_power_w", "power", 1.0),
    "sens_pv_energy": ("pv_energy_kwh", "energy", 1.0),
    "sens_grid_energy_import": ("grid_import_energy_kwh", "energy", 1.0),
    "sens_grid_energy_export": ("grid_export_energy_kwh", "energy", 1.0),
}

# Unsigned split channels for vendors without one signed sensor (e.g. SMA
# "supplied" / "absorbed"). Referenced from ``house_params.derived_entities``.
DERIVED_QUANTITY: dict[str, str] = {
    "grid_import_power_w": "power",
    "grid_export_power_w": "power",
    "ess_charge_power_w": "power",
    "ess_discharge_power_w": "power",
    "grid_power_w": "power",
    "ess_power_w": "power",
}

_BASE_UNIT = {"power": "w", "energy": "kwh", "percent": "%"}

_FORMAT = {"w": ".1f", "kw": ".4f", "mw": ".6f", "wh": ".3f", "kwh": ".6f", "mwh": ".9f"}


def entity_unit(package: ArchetypePackage, entity_id: str) -> str:
    """``unit_of_measurement`` of a fixture entity (lowercase, '' if none)."""
    for item in package.entities:
        if str(item.get("entity_id") or "").strip() != entity_id:
            continue
        attrs = item.get("attributes")
        if isinstance(attrs, dict):
            return str(attrs.get("unit_of_measurement") or "").strip().lower()
        return ""
    return ""


def base_to_native(value: float, *, quantity: str, unit: str) -> float:
    """Convert a base-unit value (W / kWh / %) into the entity's unit.

    Raises ``ValueError`` if the entity unit belongs to another quantity
    (e.g. a kWh entity mapped to a power field): the archetype is inconsistent.
    """
    factors = UNIT_FACTORS[quantity]
    key = unit or _BASE_UNIT[quantity]
    if key not in factors:
        raise ValueError(f"Unit {unit!r} is not a {quantity} unit")
    return float(value) / factors[key]


def flip_power_reading(value: float, unit: str) -> float:
    """Fault injection: show the other side of the W/kW pair.

    A kW entity then carries a watt-scale number (×1000); a W entity carries
    a kilowatt-scale number (÷1000). The entity's unit attribute stays as-is.
    """
    key = str(unit or "").strip().lower()
    if key == "kw":
        return float(value) * 1000.0
    if key == "w":
        return float(value) / 1000.0
    raise ValueError(f"unit_flip supports W/kW only, got {unit!r}")


def native_to_base(value: float, *, quantity: str, unit: str) -> float:
    """Inverse of :func:`base_to_native`."""
    factors = UNIT_FACTORS[quantity]
    key = unit or _BASE_UNIT[quantity]
    if key not in factors:
        raise ValueError(f"Unit {unit!r} is not a {quantity} unit")
    return float(value) * factors[key]


def _derived_physics(physics: dict[str, Any]) -> dict[str, float]:
    grid = float(physics.get("grid_power_w", 0.0))
    ess = float(physics.get("ess_power_w", 0.0))
    return {
        "grid_import_power_w": max(0.0, grid),
        "grid_export_power_w": max(0.0, -grid),
        # EHAL sign: + discharge, − charge.
        "ess_charge_power_w": max(0.0, -ess),
        "ess_discharge_power_w": max(0.0, ess),
        "grid_power_w": grid,
        "ess_power_w": ess,
    }


def physics_entity_values(
    package: ArchetypePackage, physics: dict[str, Any]
) -> dict[str, tuple[float, str]]:
    """Physics → ``{entity_id: (value in entity unit and vendor sign, unit)}``.

    Honors each entity's ``unit_of_measurement`` (W/kW, Wh/kWh) and the Golden
    Map ``sign`` (``negate`` = vendor sign is inverse to EHAL).
    """
    out: dict[str, tuple[float, str]] = {}
    entities = package.ehal_entities
    for field_name, (phys_key, quantity, to_base) in TELEMETRY_PROJECTION.items():
        entity_id = entities.get(field_name)
        if not entity_id or phys_key not in physics:
            continue
        unit = entity_unit(package, entity_id)
        value = base_to_native(float(physics[phys_key]) * to_base, quantity=quantity, unit=unit)
        if field_name != "sens_ess_soc" and package.ehal_sign.get(field_name) == "negate":
            value = -value
        out[entity_id] = (value, unit)

    for direction in ("charge", "discharge"):
        entity_id = battery_energy_entity_id(package, direction)
        phys_key = f"ess_{direction}_energy_kwh"
        if entity_id and phys_key in physics:
            unit = entity_unit(package, entity_id)
            out[entity_id] = (
                base_to_native(float(physics[phys_key]), quantity="energy", unit=unit),
                unit,
            )

    derived_map = package.house_params.get("derived_entities")
    if isinstance(derived_map, dict) and derived_map:
        derived = _derived_physics(physics)
        for entity_id, key in derived_map.items():
            key = str(key)
            if key not in DERIVED_QUANTITY:
                raise ValueError(f"Unknown derived physics key {key!r} for {entity_id}")
            unit = entity_unit(package, str(entity_id))
            out[str(entity_id)] = (
                base_to_native(derived[key], quantity=DERIVED_QUANTITY[key], unit=unit),
                unit,
            )
    return out


def _format_native(value: float, unit: str) -> str:
    return f"{float(value):{_FORMAT.get(unit, '.2f')}}"


def project_physics_to_store(
    store: StateWriter,
    *,
    package: ArchetypePackage,
    physics: dict[str, Any],
) -> None:
    """Write physics onto telemetry entities in each entity's unit and sign."""
    for entity_id, (value, unit) in physics_entity_values(package, physics).items():
        store.set_state(entity_id, _format_native(value, unit))

    thermal_id = str(package.house_params.get("thermal_entity_id") or "").strip()
    if thermal_id and "temp_c" in physics:
        if store.get(thermal_id) is not None:
            store.set_state(thermal_id, f"{float(physics['temp_c']):.2f}")
