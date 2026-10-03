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


def migrate_plant_ess_to_components(
    house_doc: dict[str, Any],
    components_doc: dict[str, Any],
    *,
    label: str = "house_profiles.json",
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Move plant flat ESS bindings onto the single battery's ehal_bindings."""
    house_out = dict(house_doc)
    comp_out = dict(components_doc)
    profiles = house_out.get("profiles")
    if not isinstance(profiles, list):
        stamp_data_model(house_out)
        stamp_data_model(comp_out)
        return house_out, comp_out, False

    # Collect flat ESS from any profile plant (usually one live profile)
    flat_by_profile: list[tuple[dict, dict[str, str]]] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        plant = profile.get("plant")
        if not isinstance(plant, dict):
            continue
        bindings = plant.get("ehal_bindings")
        flat = plant_flat_ess_keys(bindings if isinstance(bindings, dict) else None)
        if flat:
            flat_by_profile.append((plant, flat))

    if not flat_by_profile:
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
    for plant, flat in flat_by_profile:
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
        out["house_profiles.json"] = house_m
        out["components.json"] = comp_m
    return out


def needs_v4_migration(doc: dict[str, Any] | None) -> bool:
    version = read_data_model(doc)
    if version is None:
        return False
    return version == LEGACY_DATA_MODEL
