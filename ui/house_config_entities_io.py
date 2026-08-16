"""PV/battery/scenario CRUD and live/runtime refs for Hauskonfigurator."""
from __future__ import annotations

import json
import os
import config
from house_config.id_slug import slug_id
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
)
from settings.json_io import read_json_dict, write_json_dict

def _load_config_document() -> dict:
    from ui import house_config_io as _io

    return read_json_dict(_io.resolve_config_json_path())

def _save_config_document(data: dict) -> None:
    from ui import house_config_io as _io

    write_json_dict(_io.resolve_config_json_path(), data)
    _io.config.reinit_config()

def load_main_config() -> dict:
    """Public alias: load earnie_env config.json."""
    return _load_config_document()

def save_main_config(data: dict) -> None:
    """Public alias: persist config.json and reinit runtime config."""
    _save_config_document(data)

def _load_components_document() -> dict:
    from house_config.components_store import load_components_document

    return load_components_document(resolve_components_json_path())

def _save_components_document(data: dict) -> None:
    from house_config.components_store import save_components_document

    save_components_document(resolve_components_json_path(), data)
    config.reinit_config()

def upsert_pv_system(raw_spec: dict, *, stable_id: str = "") -> None:
    from house_config.entity_resolution import normalize_pv_system
    from house_config.label_uniqueness import assert_unique_label

    data = _load_components_document()
    systems = list(data.get("pv_systems") or [])
    taken = {str(item.get("id", "")) for item in systems if item.get("id")}
    if stable_id:
        taken.discard(stable_id)
    label = str(raw_spec.get("label", "")).strip()
    entity_id = stable_id.strip() or slug_id(label or "pv_anlage", existing=taken)
    assert_unique_label(label or entity_id, systems, exclude_id=entity_id)
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "kwp": float(raw_spec["kwp"]),
        "pv_tilt": float(raw_spec.get("pv_tilt", 25.0)),
        "pv_azimuth": float(raw_spec.get("pv_azimuth", 0.0)),
    }
    normalize_pv_system(spec, 0)
    systems = [item for item in systems if item.get("id") != entity_id]
    systems.append(spec)
    data["pv_systems"] = systems
    _save_components_document(data)

def delete_pv_system(entity_id: str) -> None:
    """Remove a PV system from components.json and scrub scenario references."""
    from ui import house_config_io as _io
    from house_config.entity_resolution import normalize_pv_system_ids

    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("PV-Anlagen-ID fehlt.")
    data = _load_components_document()
    systems = list(data.get("pv_systems") or [])
    remaining = [item for item in systems if str(item.get("id", "")).strip() != target]
    if len(remaining) == len(systems):
        raise ValueError(f"Unbekannte PV-Anlage '{target}'.")
    data["pv_systems"] = remaining
    _save_components_document(data)

    doc = _io.load_backtesting_scenarios_raw()
    changed = False
    for scenario in doc.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        settings = scenario.get("settings")
        if not isinstance(settings, dict):
            continue
        ids = normalize_pv_system_ids(settings)
        if target not in ids:
            continue
        cleaned = [pv_id for pv_id in ids if pv_id != target]
        settings.pop("pv_system_id", None)
        if cleaned:
            settings["pv_system_ids"] = cleaned
        else:
            settings.pop("pv_system_ids", None)
        changed = True
    if changed:
        _io.save_backtesting_scenarios(doc)
        config.reinit_config()

def upsert_battery(raw_spec: dict, *, stable_id: str = "") -> None:
    from house_config.entity_resolution import normalize_battery
    from house_config.label_uniqueness import assert_unique_label

    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    taken = {str(item.get("id", "")) for item in batteries if item.get("id")}
    if stable_id:
        taken.discard(stable_id)
    label = str(raw_spec.get("label", "")).strip()
    entity_id = stable_id.strip() or slug_id(label or "batterie", existing=taken)
    assert_unique_label(label or entity_id, batteries, exclude_id=entity_id)
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "battery_capacity_kwh": float(raw_spec["battery_capacity_kwh"]),
        "battery_max_power_kw": float(raw_spec["battery_max_power_kw"]),
        "battery_efficiency": float(raw_spec["battery_efficiency"]),
        "battery_min_soc": float(raw_spec["battery_min_soc"]),
        "battery_max_soc": float(raw_spec["battery_max_soc"]),
        "threshold_power": float(raw_spec.get("threshold_power", 0.05)),
        "standby_power_kw": float(raw_spec.get("standby_power_kw", 0.0) or 0.0),
    }
    existing_wear = None
    if stable_id:
        for item in batteries:
            if str(item.get("id", "")).strip() == entity_id:
                existing_wear = item.get("battery_wear")
                break
    if raw_spec.get("battery_wear") is not None:
        spec["battery_wear"] = raw_spec["battery_wear"]
    elif existing_wear is not None:
        spec["battery_wear"] = existing_wear
    else:
        spec["battery_wear"] = {"enabled": False}
    normalize_battery(spec, 0)
    batteries = [item for item in batteries if item.get("id") != entity_id]
    batteries.append(spec)
    data["batteries"] = batteries
    _save_components_document(data)

def delete_battery(entity_id: str) -> None:
    """Remove a battery from components.json and scrub scenario references."""
    from ui import house_config_io as _io
    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("Batterie-ID fehlt.")
    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    remaining = [item for item in batteries if str(item.get("id", "")).strip() != target]
    if len(remaining) == len(batteries):
        raise ValueError(f"Unbekannte Batterie '{target}'.")
    data["batteries"] = remaining
    _save_components_document(data)

    doc = _io.load_backtesting_scenarios_raw()
    changed = False
    for scenario in doc.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        settings = scenario.get("settings")
        if not isinstance(settings, dict):
            continue
        if str(settings.get("battery_id", "") or "").strip() != target:
            continue
        settings["battery_id"] = ""
        changed = True
    if changed:
        _io.save_backtesting_scenarios(doc)
        config.reinit_config()

def _live_scenario_settings() -> dict:
    from house_config.scenario_resolution import (
        find_scenario_settings,
        get_live_scenario_id,
    )

    raw_config = _load_config_document()
    live_id = get_live_scenario_id(raw_config)
    scenarios_path = config.CONFIG.backtesting_scenarios_path
    try:
        return find_scenario_settings(scenarios_path, live_id)
    except ValueError:
        return {}

def get_planning_tariff_selection() -> tuple[str, str]:
    settings = _live_scenario_settings()
    return (
        str(settings.get("import_tariff_id", "") or "").strip(),
        str(settings.get("export_tariff_id", "") or "").strip(),
    )

def save_planning_tariff_selection(import_tariff_id: str, export_tariff_id: str) -> None:
    config.update_live_scenario_settings(
        {
            "import_tariff_id": import_tariff_id.strip(),
            "export_tariff_id": export_tariff_id.strip(),
        }
    )

def get_live_scenario_refs() -> dict:
    """Entitäts-Referenzen des Live-Szenarios aus backtesting_scenarios.json."""
    from house_config.entity_resolution import normalize_pv_system_ids

    settings = _live_scenario_settings()
    return {
        "battery_id": str(settings.get("battery_id", "") or "").strip(),
        "pv_system_ids": normalize_pv_system_ids(settings),
        "import_tariff_id": str(settings.get("import_tariff_id", "") or "").strip(),
        "export_tariff_id": str(settings.get("export_tariff_id", "") or "").strip(),
        "house_profile_id": str(settings.get("house_profile_id", "") or "").strip(),
    }

def get_runtime_scenario_refs() -> dict:
    """Alias für get_live_scenario_refs (API-Stabilität)."""
    return get_live_scenario_refs()

def save_live_scenario_refs(
    *,
    battery_id: str,
    pv_system_ids: list[str],
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
) -> None:
    """Speichert Entitäts-Referenzen für das Live-Szenario."""
    cleaned = [str(item or "").strip() for item in pv_system_ids if str(item or "").strip()]
    config.update_live_scenario_settings(
        {
            "battery_id": battery_id.strip(),
            "pv_system_ids": cleaned,
            "import_tariff_id": import_tariff_id.strip(),
            "export_tariff_id": export_tariff_id.strip(),
            "house_profile_id": house_profile_id.strip(),
        }
    )

def save_live_scenario_id(scenario_id: str) -> None:
    """Setzt live_scenario_id in config.json."""
    config.set_live_scenario_id(scenario_id.strip())

def save_runtime_scenario_refs(
    *,
    battery_id: str,
    pv_system_ids: list[str],
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
) -> None:
    """Alias für save_live_scenario_refs (API-Stabilität)."""
    save_live_scenario_refs(
        battery_id=battery_id,
        pv_system_ids=pv_system_ids,
        import_tariff_id=import_tariff_id,
        export_tariff_id=export_tariff_id,
        house_profile_id=house_profile_id,
    )

def upsert_scenario(scenario: dict) -> None:
    from ui import house_config_io as _io
    from house_config.label_uniqueness import assert_unique_label

    doc = _io.load_backtesting_scenarios_raw()
    scenarios = list(doc.get("scenarios", []))
    scenario_id = str(scenario.get("id", "")).strip()
    live_id = str(config.get_live_scenario_id() or "").strip()
    payload = dict(scenario)
    if live_id and scenario_id == live_id:
        existing = next(
            (item for item in scenarios if str(item.get("id", "")).strip() == live_id),
            None,
        )
        if existing is not None:
            payload["label"] = str(
                existing.get("label") or existing.get("id") or live_id
            ).strip()
    assert_unique_label(payload.get("label"), scenarios, exclude_id=scenario_id)
    replaced = False
    updated: list[dict] = []
    for item in scenarios:
        if str(item.get("id", "")).strip() == payload["id"]:
            updated.append(payload)
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(payload)
    doc["scenarios"] = updated
    _io.save_backtesting_scenarios(doc)

def reorder_scenarios(ordered_non_live_ids: list[str]) -> None:
    """Rewrite scenarios[] as Live (if any) then non-Live in the given order."""
    from ui import house_config_io as _io
    live_id = str(config.get_live_scenario_id() or "").strip()
    requested = [str(sid).strip() for sid in ordered_non_live_ids if str(sid).strip()]
    if live_id and live_id in requested:
        raise ValueError("Das Live-Szenario kann nicht umsortiert werden.")
    doc = _io.load_backtesting_scenarios_raw()
    scenarios = list(doc.get("scenarios", []))
    by_id = {
        str(item.get("id", "")).strip(): item
        for item in scenarios
        if str(item.get("id", "")).strip()
    }
    live_item = by_id.get(live_id) if live_id else None
    non_live_ids = [sid for sid in by_id if sid != live_id]
    unknown = [sid for sid in requested if sid not in by_id or sid == live_id]
    if unknown:
        raise ValueError(f"Unbekanntes Szenario in Reihenfolge: {unknown[0]!r}.")
    missing = [sid for sid in non_live_ids if sid not in requested]
    ordered: list[dict] = []
    if live_item is not None:
        ordered.append(live_item)
    for sid in requested:
        ordered.append(by_id[sid])
    for sid in missing:
        ordered.append(by_id[sid])
    doc["scenarios"] = ordered
    _io.save_backtesting_scenarios(doc)

def delete_scenario(scenario_id: str) -> None:
    """Remove a non-live scenario from backtesting_scenarios.json."""
    from ui import house_config_io as _io
    target = str(scenario_id or "").strip()
    if not target:
        raise ValueError("Szenario-ID fehlt.")
    live_id = str(config.get_live_scenario_id() or "").strip()
    if live_id and target == live_id:
        raise ValueError("Das Live-Szenario kann nicht entfernt werden.")
    doc = _io.load_backtesting_scenarios_raw()
    scenarios = list(doc.get("scenarios", []))
    remaining = [
        item for item in scenarios if str(item.get("id", "")).strip() != target
    ]
    if len(remaining) == len(scenarios):
        raise ValueError(f"Unbekanntes Szenario '{target}'.")
    doc["scenarios"] = remaining
    _io.save_backtesting_scenarios(doc)

def preview_baseload(annual_kwh: float, consumers: list[dict]) -> dict:
    return compute_baseload_kwh(annual_kwh, consumers)

def compute_baseload_kwh(annual_kwh: float, consumers: list[dict]) -> dict:
    from house_config.baseload import compute_baseload_kwh as _compute

    return _compute(annual_kwh, consumers)
