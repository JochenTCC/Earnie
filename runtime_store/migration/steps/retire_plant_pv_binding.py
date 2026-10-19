"""Step dm4.retire_plant_pv_binding — plant PV map → inv; strip empty pv.* keys.

Bare ``plant.ehal_bindings.sens_pv_production_active`` is retired. A non-empty
plant address copies onto the sole grid-tied inverter-with-PV when that inv PV
key is missing/empty; otherwise a German blocker (no silent multi-inv split).
Also activates ``inv.*.sens_inv_power_pv`` and strips empty per-string PV keys.
"""
from __future__ import annotations

import copy
from typing import Any

from ehal.inverter_fields import inv_field
from ehal.pv_fields import pv_field
from house_config.required_signal_activation import (
    activate_required_in_components,
    activate_required_in_house,
)
from integrations.pv_attribution import grid_tied_inverters_with_pv
from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.retire_plant_pv_binding"
_PLANT_PV = "sens_pv_production_active"


def _plant_pv_address(house: dict | None) -> str | None:
    if not isinstance(house, dict):
        return None
    plant = house.get("plant")
    if not isinstance(plant, dict):
        return None
    bindings = plant.get("ehal_bindings")
    if not isinstance(bindings, dict) or _PLANT_PV not in bindings:
        return None
    return str(bindings.get(_PLANT_PV) or "").strip() or ""


def _empty_pv_production_leftovers(components: dict | None) -> bool:
    if not isinstance(components, dict):
        return False
    for pv in components.get("pv_systems") or []:
        if not isinstance(pv, dict):
            continue
        pid = str(pv.get("id") or "").strip()
        if not pid:
            continue
        bindings = pv.get("ehal_bindings")
        if not isinstance(bindings, dict):
            continue
        key = pv_field(pid, "sens_pv_production_active")
        if key in bindings and not str(bindings.get(key) or "").strip():
            return True
    return False


def _missing_inv_pv_for_attached(components: dict | None) -> bool:
    if not isinstance(components, dict):
        return False
    pv_systems = list(components.get("pv_systems") or [])
    for inv in components.get("inverters") or []:
        if not isinstance(inv, dict):
            continue
        iid = str(inv.get("id") or "").strip()
        if not iid:
            continue
        attached = [
            p
            for p in pv_systems
            if isinstance(p, dict)
            and str(p.get("inverter_id") or "").strip() == iid
        ]
        if not attached:
            continue
        key = inv_field(iid, "sens_inv_power_pv")
        bindings = inv.get("ehal_bindings")
        if not isinstance(bindings, dict) or key not in bindings:
            return True
    return False


def detect(docs: Docs) -> bool:
    house = docs.get("house_profiles.json")
    components = docs.get("components.json")
    if isinstance(house, dict):
        plant = house.get("plant")
        if isinstance(plant, dict):
            bindings = plant.get("ehal_bindings")
            if isinstance(bindings, dict) and _PLANT_PV in bindings:
                return True
    return _empty_pv_production_leftovers(components) or _missing_inv_pv_for_attached(
        components
    )


def _copy_plant_to_sole_inv(
    components: dict,
    address: str,
) -> tuple[dict, Blocker | None]:
    """Copy plant PV address onto sole eligible inv PV key, or return blocker."""
    inverters = [i for i in (components.get("inverters") or []) if isinstance(i, dict)]
    pv_systems = [p for p in (components.get("pv_systems") or []) if isinstance(p, dict)]
    eligible = grid_tied_inverters_with_pv(inverters, pv_systems)
    if len(eligible) != 1:
        return components, Blocker(
            step_id=STEP_ID,
            message_de=(
                "Anlagen-PV-Mapping (plant.ehal_bindings.sens_pv_production_active) "
                "kann nicht automatisch übernommen werden: es gibt "
                f"{len(eligible)} netzgekoppelte Wechselrichter mit PV. "
                "Bitte je Wechselrichter inv.{{id}}.sens_inv_power_pv manuell mappen "
                "und das flache Anlagen-Mapping entfernen."
            ),
        )
    inv = eligible[0]
    iid = str(inv.get("id") or "").strip()
    key = inv_field(iid, "sens_inv_power_pv")
    bindings = dict(inv.get("ehal_bindings") or {})
    existing = str(bindings.get(key) or "").strip()
    if existing and existing != address:
        return components, Blocker(
            step_id=STEP_ID,
            message_de=(
                f"Anlagen-PV-Mapping „{address}“ kollidiert mit bestehendem "
                f"{key}=„{existing}“. Bitte eines der Mappings bereinigen."
            ),
        )
    out = copy.deepcopy(components)
    new_invs: list[Any] = []
    for item in out.get("inverters") or []:
        if not isinstance(item, dict):
            new_invs.append(item)
            continue
        if str(item.get("id") or "").strip() != iid:
            new_invs.append(item)
            continue
        row = dict(item)
        bind = dict(row.get("ehal_bindings") or {})
        bind[key] = address
        row["ehal_bindings"] = bind
        new_invs.append(row)
    out["inverters"] = new_invs
    return out, None


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    changed: list[str] = []
    house = out.get("house_profiles.json")
    components = out.get("components.json")

    address = _plant_pv_address(house if isinstance(house, dict) else None)
    if address and isinstance(components, dict):
        components, blocker = _copy_plant_to_sole_inv(components, address)
        if blocker is not None:
            return StepResult(docs=docs, changed_files=(), blockers=(blocker,))
        out["components.json"] = components

    if isinstance(house, dict):
        updated_h = activate_required_in_house(house)
        stamp_data_model(updated_h)
        out["house_profiles.json"] = updated_h
        changed.append("house_profiles.json")

    if isinstance(components, dict):
        updated_c = activate_required_in_components(
            out.get("components.json")
            if isinstance(out.get("components.json"), dict)
            else components
        )
        stamp_data_model(updated_c)
        out["components.json"] = updated_c
        if "components.json" not in changed:
            changed.append("components.json")

    return StepResult(docs=out, changed_files=tuple(changed))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Anlagen-PV-Binding auf Wechselrichter übernehmen",
    files=("house_profiles.json", "components.json"),
    detect=detect,
    apply=apply,
    questions=(),
)
