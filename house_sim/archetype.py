"""Load hand-authored archetype fixtures for the HA Lab bench."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from house_sim.state_store import StateStore

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class ArchetypePackage:
    name: str
    root: Path
    entities: list[dict[str, Any]]
    ehal_entities: dict[str, str]
    ehal_sign: dict[str, str]
    house_params: dict[str, Any]
    pv_series_kw: list[float]

    def build_store(self) -> StateStore:
        return StateStore(self.entities)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_archetype(name: str, *, fixtures_dir: Path | None = None) -> ArchetypePackage:
    root = (fixtures_dir or FIXTURES_DIR) / name
    if not root.is_dir():
        raise FileNotFoundError(f"Archetype fixture not found: {root}")

    entities_doc = _read_json(root / "entities.json")
    if isinstance(entities_doc, dict):
        entities = list(entities_doc.get("entities") or [])
    elif isinstance(entities_doc, list):
        entities = list(entities_doc)
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
    )


def project_physics_to_store(
    store: StateStore,
    *,
    package: ArchetypePackage,
    physics: dict[str, Any],
) -> None:
    """Write physics fields onto mapped telemetry entities (Mode A IDs)."""
    entities = package.ehal_entities
    mapping = {
        "sens_pv_production_active": ("pv_kw", "kW"),
        "sens_ess_soc": ("soc_pct", "%"),
        "sens_ess_power": ("ess_power_w", "W"),
        "sens_grid_power_active": ("grid_power_w", "W"),
        "sens_evcs_active_power": ("evcs_power_w", "W"),
    }
    for field_name, (phys_key, _unit) in mapping.items():
        entity_id = entities.get(field_name)
        if not entity_id or phys_key not in physics:
            continue
        value = physics[phys_key]
        if phys_key == "pv_kw":
            store.set_state(entity_id, f"{float(value):.4f}")
        elif phys_key == "soc_pct":
            store.set_state(entity_id, f"{float(value):.2f}")
        else:
            store.set_state(entity_id, f"{float(value):.1f}")

    thermal_id = str(package.house_params.get("thermal_entity_id") or "").strip()
    if thermal_id and "temp_c" in physics:
        if store.get(thermal_id) is not None:
            store.set_state(thermal_id, f"{float(physics['temp_c']):.2f}")
