"""PV/inverter/scenario CRUD and live/runtime refs for Hauskonfigurator.

Battery CRUD lives in ``ui.house_config_battery_io`` and is re-exported here.
"""
from __future__ import annotations

import config
from runtime_store.persist_paths import resolve_components_json_path
from settings.json_io import read_json_dict, write_json_dict
from ui.house_config_battery_io import (  # noqa: F401 — re-exports (public CRUD API)
    _attached_ids_from_battery,
    _rewrite_shadow_battery_overlay,
    _scrub_battery_ids_from_scenarios,
    delete_battery,
    sync_consumers_from_powerstation_attached,
    sync_powerstation_attached_from_consumers,
    upsert_battery,
)


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

def _pv_bindings_src(
    raw_spec: dict, existing: dict | None, *, old_id: str, entity_id: str
):
    """ehal_bindings to persist for a PV system (disk bindings kept when the form sends none)."""
    from house_config.entity_id_lock import rewrite_pv_bindings_slug

    bindings_src = raw_spec.get("ehal_bindings")
    if (
        not (
            isinstance(bindings_src, dict)
            and bindings_src
        )
        and isinstance(existing, dict)
    ):
        bindings_src = existing.get("ehal_bindings")
    if old_id and old_id != entity_id:
        bindings_src = rewrite_pv_bindings_slug(
            bindings_src if isinstance(bindings_src, dict) else {},
            old_id=old_id,
            new_id=entity_id,
        )
    return bindings_src


def _replace_entity_in_list(items: list, save_spec: dict, ids: set[str]) -> list:
    """``items`` without the entries matching ``ids``, plus ``save_spec``."""
    kept = [
        item for item in items if str(item.get("id", "")).strip() not in ids
    ]
    kept.append(save_spec)
    return kept


def upsert_pv_system(
    raw_spec: dict,
    *,
    stable_id: str = "",
    force_id_from_label: bool = False,
) -> str:
    """Upsert PV system; return the persisted id (may rename when unlocking)."""
    from house_config.entity_id_lock import (
        ID_LOCKED_KEY,
        ID_PROVISIONAL_LABEL_KEY,
        resolve_id_on_save,
    )
    from house_config.entity_resolution import normalize_pv_system
    from house_config.label_uniqueness import assert_unique_label

    data = _load_components_document()
    systems = list(data.get("pv_systems") or [])
    old_id = str(stable_id or "").strip()
    existing = next(
        (
            item
            for item in systems
            if isinstance(item, dict) and str(item.get("id", "")).strip() == old_id
        ),
        None,
    )
    taken = {str(item.get("id", "")) for item in systems if item.get("id")}
    label = str(raw_spec.get("label", "")).strip()
    entity_id, id_locked, provisional = resolve_id_on_save(
        label=label,
        stable_id=old_id,
        existing=existing,
        taken=taken,
        provisional_from_ui=str(raw_spec.get(ID_PROVISIONAL_LABEL_KEY) or "").strip(),
        force_from_label=force_id_from_label,
    )
    assert_unique_label(label or entity_id, systems, exclude_id=entity_id)
    inverter_id = str(raw_spec.get("inverter_id") or "").strip()
    if not inverter_id and isinstance(existing, dict):
        inverter_id = str(existing.get("inverter_id") or "").strip()
    if not inverter_id:
        raise ValueError("PV-Feld: inverter_id fehlt.")
    bindings_src = _pv_bindings_src(
        raw_spec, existing, old_id=old_id, entity_id=entity_id
    )
    # Wire shape for components.json (kwp); normalize_pv_system uses pv_kwp at runtime.
    save_spec = {
        "id": entity_id,
        "label": label or entity_id,
        "kwp": float(raw_spec["kwp"]),
        "pv_tilt": float(raw_spec.get("pv_tilt", 25.0)),
        "pv_azimuth": float(raw_spec.get("pv_azimuth", 0.0)),
        "inverter_id": inverter_id,
        ID_LOCKED_KEY: id_locked,
    }
    if isinstance(bindings_src, dict):
        save_spec["ehal_bindings"] = bindings_src
    if not id_locked and provisional:
        save_spec[ID_PROVISIONAL_LABEL_KEY] = provisional
    normalize_pv_system(save_spec, 0)  # validate before persist
    from house_config.required_signal_activation import (
        activate_inverter_required,
        activate_pv_system_required,
    )

    save_spec = activate_pv_system_required(save_spec)
    if old_id and old_id != entity_id:
        _rewrite_id_list_in_scenarios("pv_system_ids", old_id, entity_id)
    data["pv_systems"] = _replace_entity_in_list(systems, save_spec, {entity_id, old_id})
    # Re-activate inverter required keys (sens_inv_power_pv) after PV attach/detach.
    invs = list(data.get("inverters") or [])
    refreshed: list[dict] = []
    for inv in invs:
        if not isinstance(inv, dict):
            continue
        refreshed.append(
            activate_inverter_required(inv, pv_systems=data.get("pv_systems") or [])
        )
    data["inverters"] = refreshed
    _save_components_document(data)
    return entity_id


def _inverter_bindings_src(
    raw_spec: dict, existing: dict | None, *, old_id: str, entity_id: str
):
    """ehal_bindings to persist for an inverter (disk bindings kept when the form sends none)."""
    from house_config.entity_id_lock import rewrite_inv_bindings_slug

    bindings_src = raw_spec.get("ehal_bindings")
    if (
        not (
            isinstance(bindings_src, dict)
            and any(str(v or "").strip() for v in bindings_src.values())
        )
        and isinstance(existing, dict)
        and isinstance(existing.get("ehal_bindings"), dict)
    ):
        bindings_src = existing.get("ehal_bindings")
    if old_id and old_id != entity_id:
        bindings_src = rewrite_inv_bindings_slug(
            bindings_src if isinstance(bindings_src, dict) else {},
            old_id=old_id,
            new_id=entity_id,
        )
    return bindings_src


def _inverter_save_spec(
    raw_spec: dict,
    existing: dict | None,
    *,
    entity_id: str,
    label: str,
    id_locked: bool,
) -> dict:
    """Wire shape of the inverter entry (without bindings / provisional label)."""
    from house_config.entity_id_lock import ID_LOCKED_KEY
    from house_config.inverter import DEFAULT_INVERTER_EFFICIENCY

    efficiency_raw = raw_spec.get("efficiency")
    if efficiency_raw in (None, "") and isinstance(existing, dict):
        efficiency_raw = existing.get("efficiency")
    if efficiency_raw in (None, ""):
        efficiency_raw = DEFAULT_INVERTER_EFFICIENCY
    save_spec: dict = {
        "id": entity_id,
        "label": label or entity_id,
        "type": str(raw_spec.get("type") or "hybrid").strip().lower(),
        "ac_connection": str(
            raw_spec.get("ac_connection") or "grid_tied"
        ).strip().lower(),
        "control": str(raw_spec.get("control") or "full").strip().lower(),
        "efficiency": float(efficiency_raw),
        ID_LOCKED_KEY: id_locked,
    }
    for field in ("max_ac_power_kw", "max_pv_input_kw", "max_ac_charge_kw"):
        if field in raw_spec and raw_spec[field] not in (None, ""):
            save_spec[field] = float(raw_spec[field])
    owned_by = str(raw_spec.get("owned_by") or "").strip()
    if not owned_by and isinstance(existing, dict):
        owned_by = str(existing.get("owned_by") or "").strip()
    if owned_by:
        save_spec["owned_by"] = owned_by
    return save_spec


def upsert_inverter(
    raw_spec: dict,
    *,
    stable_id: str = "",
    force_id_from_label: bool = False,
) -> str:
    """Upsert inverter; return the persisted id (may rename when unlocking)."""
    from house_config.entity_id_lock import ID_PROVISIONAL_LABEL_KEY, resolve_id_on_save
    from house_config.inverter import normalize_inverter
    from house_config.label_uniqueness import assert_unique_label

    data = _load_components_document()
    inverters = list(data.get("inverters") or [])
    old_id = str(stable_id or "").strip()
    existing = next(
        (
            item
            for item in inverters
            if isinstance(item, dict) and str(item.get("id", "")).strip() == old_id
        ),
        None,
    )
    taken = {str(item.get("id", "")) for item in inverters if item.get("id")}
    label = str(raw_spec.get("label", "")).strip()
    entity_id, id_locked, provisional = resolve_id_on_save(
        label=label,
        stable_id=old_id,
        existing=existing,
        taken=taken,
        provisional_from_ui=str(raw_spec.get(ID_PROVISIONAL_LABEL_KEY) or "").strip(),
        force_from_label=force_id_from_label,
    )
    assert_unique_label(label or entity_id, inverters, exclude_id=entity_id)
    bindings_src = _inverter_bindings_src(
        raw_spec, existing, old_id=old_id, entity_id=entity_id
    )
    save_spec = _inverter_save_spec(
        raw_spec, existing, entity_id=entity_id, label=label, id_locked=id_locked
    )
    if isinstance(bindings_src, dict):
        save_spec["ehal_bindings"] = bindings_src
    if not id_locked and provisional:
        save_spec[ID_PROVISIONAL_LABEL_KEY] = provisional
    normalize_inverter(save_spec, 0)
    from house_config.required_signal_activation import activate_inverter_required

    save_spec = activate_inverter_required(
        save_spec, pv_systems=data.get("pv_systems") or []
    )
    if old_id and old_id != entity_id:
        _rewrite_inverter_refs_in_doc(data, old_id, entity_id)
    data["inverters"] = _replace_entity_in_list(
        inverters, save_spec, {entity_id, old_id}
    )
    _save_components_document(data)
    return entity_id


def _rewrite_inverter_refs_in_doc(data: dict, old_id: str, new_id: str) -> None:
    """Point batteries/PV inverter_id from old_id to new_id in-place."""
    for key in ("batteries", "pv_systems"):
        rows = list(data.get(key) or [])
        new_rows: list[dict] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if str(row.get("inverter_id") or "").strip() == old_id:
                row["inverter_id"] = new_id
            new_rows.append(row)
        data[key] = new_rows


def delete_inverter(entity_id: str) -> None:
    """Remove an inverter; fail if batteries/PV still reference it."""
    from house_config.inverter_lifecycle import inverter_refs_blocking_delete

    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("Wechselrichter-ID fehlt.")
    data = _load_components_document()
    inverters = list(data.get("inverters") or [])
    remaining = [
        item for item in inverters if str(item.get("id", "")).strip() != target
    ]
    if len(remaining) == len(inverters):
        raise ValueError(f"Unbekannter Wechselrichter '{target}'.")
    refs = inverter_refs_blocking_delete(
        inverter_id=target,
        batteries=list(data.get("batteries") or []),
        pv_systems=list(data.get("pv_systems") or []),
    )
    if refs:
        raise ValueError(
            f"Wechselrichter '{target}' wird noch referenziert: "
            + ", ".join(refs)
            + "."
        )
    data["inverters"] = remaining
    _save_components_document(data)

def delete_pv_system(entity_id: str) -> None:
    """Remove a PV system from components.json and scrub scenario references."""
    from ui import house_config_io as _io
    from house_config.entity_resolution import normalize_pv_system_ids

    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("PV-Feld-ID fehlt.")
    data = _load_components_document()
    systems = list(data.get("pv_systems") or [])
    remaining = [item for item in systems if str(item.get("id", "")).strip() != target]
    if len(remaining) == len(systems):
        raise ValueError(f"Unbekanntes PV-Feld '{target}'.")
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











def _rewrite_id_list_in_scenarios(key: str, old_id: str, new_id: str) -> bool:
    """Replace ``old_id`` with ``new_id`` in scenario settings lists."""
    from ui import house_config_io as _io

    if not old_id or not new_id or old_id == new_id:
        return False
    doc = _io.load_backtesting_scenarios_raw()
    changed = False
    for scenario in doc.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        settings = scenario.get("settings")
        if not isinstance(settings, dict):
            continue
        raw_ids = settings.get(key)
        if not isinstance(raw_ids, list):
            continue
        before = [str(item or "").strip() for item in raw_ids if str(item or "").strip()]
        after = [new_id if item == old_id else item for item in before]
        # Dedupe while preserving order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in after:
            if item in seen:
                continue
            seen.add(item)
            cleaned.append(item)
        if cleaned == before:
            continue
        settings[key] = cleaned
        changed = True
    if changed:
        _io.save_backtesting_scenarios(doc)
    return changed






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
    from house_config.entity_resolution import (
        normalize_battery_ids,
        normalize_pv_system_ids,
    )

    settings = dict(_live_scenario_settings())
    if "battery_id" in settings and "battery_ids" not in settings:
        bid = str(settings.pop("battery_id") or "").strip()
        settings["battery_ids"] = [bid] if bid else []
    else:
        settings.pop("battery_id", None)
    battery_ids = normalize_battery_ids(settings)
    return {
        "battery_ids": battery_ids,
        # Compatibility for call sites still reading the primary battery.
        "battery_id": battery_ids[0] if battery_ids else "",
        "pv_system_ids": normalize_pv_system_ids(settings),
        "import_tariff_id": str(settings.get("import_tariff_id", "") or "").strip(),
        "export_tariff_id": str(settings.get("export_tariff_id", "") or "").strip(),
        "house_profile_id": str(settings.get("house_profile_id", "") or "").strip(),
    }

def save_live_scenario_refs(
    *,
    battery_ids: list[str] | None = None,
    battery_id: str = "",
    pv_system_ids: list[str],
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
) -> None:
    """Speichert Entitäts-Referenzen für das Live-Szenario."""
    cleaned_pv = [
        str(item or "").strip() for item in pv_system_ids if str(item or "").strip()
    ]
    cleaned_bat = [
        str(item or "").strip()
        for item in (battery_ids or [])
        if str(item or "").strip()
    ]
    if not cleaned_bat:
        legacy = str(battery_id or "").strip()
        if legacy:
            cleaned_bat = [legacy]
    config.update_live_scenario_settings(
        {
            "battery_ids": cleaned_bat,
            "pv_system_ids": cleaned_pv,
            "import_tariff_id": import_tariff_id.strip(),
            "export_tariff_id": export_tariff_id.strip(),
            "house_profile_id": house_profile_id.strip(),
        }
    )

def save_live_scenario_id(scenario_id: str) -> None:
    """Setzt live_scenario_id in config.json."""
    config.set_live_scenario_id(scenario_id.strip())

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
