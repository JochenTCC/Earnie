"""Migrate Earnie config documents from earnie_data_model 3 → 4 (2.7.c multi-ESS)."""
from __future__ import annotations

from typing import Any

from ehal.ess_fields import ess_field, plant_flat_ess_keys
from house_config.battery_kind import DEFAULT_BATTERY_KIND
from runtime_store.data_model import (
    CURRENT_DATA_MODEL,
    DATA_MODEL_KEY,
    read_data_model,
    stamp_data_model,
)

LEGACY_DATA_MODEL = 3


class MigrateV4Error(ValueError):
    """Raised when a v3→v4 migration cannot proceed safely."""


def _migrate_scenario_settings(settings: dict) -> bool:
    """battery_id → battery_ids. Returns True if changed."""
    if not isinstance(settings, dict):
        return False
    if "battery_id" not in settings:
        if "battery_ids" not in settings:
            settings["battery_ids"] = []
            return True
        return False
    raw = settings.pop("battery_id")
    bat_id = str(raw or "").strip()
    existing = settings.get("battery_ids")
    if isinstance(existing, list) and existing:
        return True
    settings["battery_ids"] = [bat_id] if bat_id else []
    return True


def migrate_scenarios_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Upgrade backtesting_scenarios.json in place (idempotent)."""
    out = dict(doc)
    changed = False
    scenarios = out.get("scenarios")
    if isinstance(scenarios, list):
        for entry in scenarios:
            if not isinstance(entry, dict):
                continue
            settings = entry.get("settings")
            if isinstance(settings, dict) and _migrate_scenario_settings(settings):
                changed = True
    version = read_data_model(out)
    if version != CURRENT_DATA_MODEL:
        stamp_data_model(out)
        changed = True
    return out if changed or version != CURRENT_DATA_MODEL else out


def migrate_components_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Default missing batteries[].kind; stamp data model."""
    out = dict(doc)
    batteries = out.get("batteries")
    if isinstance(batteries, list):
        for bat in batteries:
            if not isinstance(bat, dict):
                continue
            if not str(bat.get("kind") or "").strip():
                bat["kind"] = DEFAULT_BATTERY_KIND
            if "ehal_bindings" not in bat or bat.get("ehal_bindings") is None:
                bat["ehal_bindings"] = {}
    stamp_data_model(out)
    return out


def _target_battery_for_plant_ess(
    components_doc: dict[str, Any] | None,
    *,
    label: str,
) -> str:
    """Pick unambiguous battery id for plant ESS migrate; raise if ambiguous."""
    batteries = []
    if isinstance(components_doc, dict):
        raw = components_doc.get("batteries")
        if isinstance(raw, list):
            batteries = [b for b in raw if isinstance(b, dict) and str(b.get("id") or "").strip()]
    if len(batteries) == 0:
        raise MigrateV4Error(
            f"{label}: plant has flat ESS ehal_bindings but components.json "
            "has no batteries[] to attach them to."
        )
    if len(batteries) > 1:
        raise MigrateV4Error(
            f"{label}: plant has flat ESS ehal_bindings and "
            f"{len(batteries)} batteries — cannot choose target automatically; "
            "move bindings to batteries[].ehal_bindings (ess.{{slug}}.*) manually."
        )
    return str(batteries[0]["id"]).strip()


_SOURCE_SELECT_KIND = "set_ess_source_select"
# Phase-1 (single-battery ESS move) skips Quellenwahl; phase-2 targets standby_backup.
_PLANT_ESS_PHASE2_ONLY = frozenset({_SOURCE_SELECT_KIND})


def _iter_plants(house_doc: dict[str, Any]) -> list[dict]:
    """Top-level plant plus legacy nested ``profiles[].plant``."""
    plants: list[dict] = []
    top = house_doc.get("plant")
    if isinstance(top, dict):
        plants.append(top)
    profiles = house_doc.get("profiles")
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            plant = profile.get("plant")
            if isinstance(plant, dict):
                plants.append(plant)
    return plants


def _collect_plants_with_flat_ess(
    house_doc: dict[str, Any],
) -> list[tuple[dict, dict[str, str]]]:
    """Find plant dicts that still hold phase-1 movable flat ESS bindings.

    Supports live top-level ``house["plant"]`` and legacy nested
    ``profiles[].plant`` (list-shaped profiles). Quellenwahl is phase-2 only.
    """
    found: list[tuple[dict, dict[str, str]]] = []
    for plant in _iter_plants(house_doc):
        bindings = plant.get("ehal_bindings")
        flat = plant_flat_ess_keys(bindings if isinstance(bindings, dict) else None)
        movable = {k: v for k, v in flat.items() if k not in _PLANT_ESS_PHASE2_ONLY}
        if movable:
            found.append((plant, movable))
    return found


def _collect_plants_with_any_flat_ess(
    house_doc: dict[str, Any],
) -> list[tuple[dict, dict[str, str]]]:
    """All plant-flat ESS keys including Quellenwahl (residual checks)."""
    found: list[tuple[dict, dict[str, str]]] = []
    for plant in _iter_plants(house_doc):
        bindings = plant.get("ehal_bindings")
        flat = plant_flat_ess_keys(bindings if isinstance(bindings, dict) else None)
        if flat:
            found.append((plant, flat))
    return found

def _physical_standby_backup_batteries(
    components_doc: dict[str, Any],
) -> list[dict]:
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        ROLE_STANDBY_BACKUP,
        is_powerstation,
    )

    raw = components_doc.get("batteries")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for bat in raw:
        if not isinstance(bat, dict) or not is_powerstation(bat):
            continue
        if str(bat.get("role") or "") != ROLE_STANDBY_BACKUP:
            continue
        if str(bat.get("backing") or "") != BACKING_PHYSICAL:
            continue
        if not str(bat.get("id") or "").strip():
            continue
        out.append(bat)
    return out


def _plant_source_select_address(plant: dict) -> str:
    bindings = plant.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return ""
    return str(bindings.get(_SOURCE_SELECT_KIND) or "").strip()


def migrate_plant_source_select_to_standby(
    house_doc: dict[str, Any],
    components_doc: dict[str, Any],
    *,
    label: str = "house_profiles.json",
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Move plant ``set_ess_source_select`` onto the physical standby_backup battery.

    Requires exactly one physical ``role: standby_backup`` when plant still owns
    the binding. Idempotent when plant has no Quellenwahl.
    """
    house_out = dict(house_doc)
    comp_out = dict(components_doc)
    plants_with = [
        p for p in _iter_plants(house_out) if _plant_source_select_address(p)
    ]
    if not plants_with:
        stamp_data_model(house_out)
        stamp_data_model(comp_out)
        return house_out, migrate_components_doc(comp_out), False

    standbys = _physical_standby_backup_batteries(comp_out)
    if len(standbys) == 0:
        raise MigrateV4Error(
            f"{label}: plant has set_ess_source_select but no physical "
            "standby_backup battery to attach it to."
        )
    if len(standbys) > 1:
        ids = ", ".join(str(b.get("id") or "").strip() for b in standbys)
        raise MigrateV4Error(
            f"{label}: plant has set_ess_source_select and "
            f"{len(standbys)} physical standby_backup batteries ({ids}) — "
            "move ess.{{slug}}.set_ess_source_select manually."
        )
    target_bat = standbys[0]
    target_id = str(target_bat.get("id") or "").strip()
    pattern_key = ess_field(target_id, _SOURCE_SELECT_KIND)
    merged: dict[str, str] = dict(target_bat.get("ehal_bindings") or {})
    changed = False
    for plant in plants_with:
        address = _plant_source_select_address(plant)
        if not address:
            continue
        if pattern_key not in merged:
            merged[pattern_key] = address
            changed = True
        bindings = plant.get("ehal_bindings")
        if isinstance(bindings, dict) and _SOURCE_SELECT_KIND in bindings:
            bindings.pop(_SOURCE_SELECT_KIND, None)
            changed = True
    if changed:
        target_bat["ehal_bindings"] = merged
        if not str(target_bat.get("kind") or "").strip():
            target_bat["kind"] = DEFAULT_BATTERY_KIND
    stamp_data_model(house_out)
    stamp_data_model(comp_out)
    return house_out, migrate_components_doc(comp_out), changed


def migrate_plant_ess_to_components(
    house_doc: dict[str, Any],
    components_doc: dict[str, Any],
    *,
    label: str = "house_profiles.json",
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Move plant flat ESS bindings onto the single battery's ehal_bindings."""
    house_out = dict(house_doc)
    comp_out = dict(components_doc)
    flat_plants = _collect_plants_with_flat_ess(house_out)

    if not flat_plants:
        stamp_data_model(house_out)
        stamp_data_model(comp_out)
        return house_out, migrate_components_doc(comp_out), False

    target_id = _target_battery_for_plant_ess(comp_out, label=label)
    batteries = comp_out.get("batteries")
    if not isinstance(batteries, list):
        raise MigrateV4Error(f"{label}: components.batteries missing.")
    target_bat = None
    for bat in batteries:
        if isinstance(bat, dict) and str(bat.get("id") or "").strip() == target_id:
            target_bat = bat
            break
    if target_bat is None:
        raise MigrateV4Error(f"{label}: battery '{target_id}' not found in components.")

    merged: dict[str, str] = dict(target_bat.get("ehal_bindings") or {})
    for plant, flat in flat_plants:
        for kind, address in flat.items():
            key = ess_field(target_id, kind)
            if key not in merged:
                merged[key] = address
        bindings = plant.get("ehal_bindings")
        if isinstance(bindings, dict):
            for kind in list(flat.keys()):
                bindings.pop(kind, None)

    target_bat["ehal_bindings"] = merged
    if not str(target_bat.get("kind") or "").strip():
        target_bat["kind"] = DEFAULT_BATTERY_KIND
    stamp_data_model(house_out)
    stamp_data_model(comp_out)
    return house_out, migrate_components_doc(comp_out), True


def residual_plant_flat_ess_keys(house_doc: dict[str, Any] | None) -> list[str]:
    """Flat ESS keys still on plant after migrate (incl. Quellenwahl)."""
    keys: list[str] = []
    for plant, flat in _collect_plants_with_any_flat_ess(
        house_doc if isinstance(house_doc, dict) else {}
    ):
        del plant  # only need keys
        keys.extend(sorted(flat))
    return sorted(set(keys))
def migrate_document(doc: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Migrate a single document by kind: scenarios|components|generic."""
    version = read_data_model(doc)
    if version is not None and version >= CURRENT_DATA_MODEL:
        if kind == "scenarios":
            # Still normalize battery_id if a v4 doc was hand-edited wrongly
            out = migrate_scenarios_doc(dict(doc))
            return out
        if kind == "components":
            return migrate_components_doc(dict(doc))
        out = dict(doc)
        stamp_data_model(out)
        return out
    if version is not None and version not in (LEGACY_DATA_MODEL, CURRENT_DATA_MODEL):
        raise MigrateV4Error(
            f"earnie_data_model={version} cannot be migrated to {CURRENT_DATA_MODEL}."
        )
    if kind == "scenarios":
        return migrate_scenarios_doc(dict(doc))
    if kind == "components":
        return migrate_components_doc(dict(doc))
    out = dict(doc)
    stamp_data_model(out)
    return out


def migrate_pack_docs(
    docs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Migrate a pack mapping filename → doc. Mutates copies; returns new map."""
    out: dict[str, dict[str, Any]] = {}
    components = docs.get("components.json")
    house = docs.get("house_profiles.json")
    for name, doc in docs.items():
        if not isinstance(doc, dict):
            continue
        if name == "backtesting_scenarios.json":
            out[name] = migrate_document(doc, kind="scenarios")
        elif name == "components.json":
            out[name] = migrate_document(doc, kind="components")
        else:
            out[name] = migrate_document(doc, kind="generic")

    if isinstance(house, dict) and isinstance(components, dict):
        house_m = out.get("house_profiles.json", house)
        comp_m = out.get("components.json", components)
        house_m, comp_m, _ = migrate_plant_ess_to_components(house_m, comp_m)
        house_m, comp_m, _ = migrate_plant_source_select_to_standby(house_m, comp_m)
        out["house_profiles.json"] = house_m
        out["components.json"] = comp_m
    return out


def needs_v4_migration(doc: dict[str, Any] | None) -> bool:
    version = read_data_model(doc)
    if version is None:
        return False
    return version == LEGACY_DATA_MODEL
