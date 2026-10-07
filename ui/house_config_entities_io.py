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
    # Wire shape for components.json (kwp); normalize_pv_system uses pv_kwp at runtime.
    save_spec = {
        "id": entity_id,
        "label": label or entity_id,
        "kwp": float(raw_spec["kwp"]),
        "pv_tilt": float(raw_spec.get("pv_tilt", 25.0)),
        "pv_azimuth": float(raw_spec.get("pv_azimuth", 0.0)),
        ID_LOCKED_KEY: id_locked,
    }
    if not id_locked and provisional:
        save_spec[ID_PROVISIONAL_LABEL_KEY] = provisional
    normalize_pv_system(save_spec, 0)  # validate before persist
    if old_id and old_id != entity_id:
        _rewrite_id_list_in_scenarios("pv_system_ids", old_id, entity_id)
    systems = [
        item
        for item in systems
        if str(item.get("id", "")).strip() not in {entity_id, old_id}
    ]
    systems.append(save_spec)
    data["pv_systems"] = systems
    _save_components_document(data)
    return entity_id

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

def _attached_ids_from_battery(item: dict) -> list[str]:
    ids = [
        str(cid).strip()
        for cid in (item.get("attached_consumer_ids") or [])
        if str(cid or "").strip()
    ]
    if ids:
        return ids
    singular = str(item.get("attached_consumer_id") or "").strip()
    return [singular] if singular else []


def sync_powerstation_attached_from_consumers(consumers: list[dict]) -> None:
    """Write attached_consumer_ids on powerstations linked via reserve mode."""
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        reserve_links_from_consumers,
    )

    links = reserve_links_from_consumers(consumers)
    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    changed = False
    for item in batteries:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id") or "").strip()
        if str(item.get("type") or "house").strip().lower() != "powerstation":
            continue
        # Authoritative from consumers: missing key → clear attached list.
        new_ids = list(links.get(bid, []))
        backing = str(item.get("backing") or "virtual").strip().lower()
        if backing == BACKING_PHYSICAL and len(new_ids) > 1:
            new_ids = new_ids[:1]
        old_ids = _attached_ids_from_battery(item)
        if old_ids != new_ids:
            item["attached_consumer_ids"] = new_ids
            item["attached_consumer_id"] = new_ids[0] if new_ids else ""
            changed = True
    if changed:
        data["batteries"] = batteries
        _save_components_document(data)


def _strip_attached_from_other_powerstations(
    powerstation_id: str, claimed: set[str]
) -> None:
    """Remove claimed consumer ids from sibling powerstation attached lists."""
    if not claimed:
        return
    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    changed = False
    for item in batteries:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id") or "").strip()
        if bid == powerstation_id:
            continue
        if str(item.get("type") or "house").strip().lower() != "powerstation":
            continue
        old_ids = _attached_ids_from_battery(item)
        new_ids = [cid for cid in old_ids if cid not in claimed]
        if new_ids != old_ids:
            item["attached_consumer_ids"] = new_ids
            item["attached_consumer_id"] = new_ids[0] if new_ids else ""
            changed = True
    if changed:
        data["batteries"] = batteries
        _save_components_document(data)


def sync_consumers_from_powerstation_attached(
    powerstation_id: str,
    attached_ids: list[str],
) -> None:
    """Battery-form authoritative: push attached list → house-profile consumers."""
    from house_config.powerstation import MODE_ADVICE, MODE_RESERVE
    from ui import house_config_io as _io

    ps_id = str(powerstation_id or "").strip()
    if not ps_id:
        return
    wanted = {str(cid).strip() for cid in attached_ids if str(cid or "").strip()}
    doc = _io.load_house_profiles()
    raw_profiles = doc.get("profiles") or {}
    if isinstance(raw_profiles, dict):
        profiles = list(raw_profiles.values())
    elif isinstance(raw_profiles, list):
        profiles = list(raw_profiles)
    else:
        profiles = []
    changed = False
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            cid = str(consumer.get("id") or "").strip()
            if not cid:
                continue
            rec_raw = consumer.get("appliance_recommendation")
            rec = dict(rec_raw) if isinstance(rec_raw, dict) else {}
            current_ps = str(rec.get("powerstation_id") or "").strip()
            if cid in wanted:
                if (
                    str(rec.get("mode") or "").strip().lower() != MODE_RESERVE
                    or current_ps != ps_id
                ):
                    rec["mode"] = MODE_RESERVE
                    rec["powerstation_id"] = ps_id
                    consumer["appliance_recommendation"] = rec
                    changed = True
            elif current_ps == ps_id:
                rec["mode"] = MODE_ADVICE
                rec.pop("powerstation_id", None)
                consumer["appliance_recommendation"] = rec
                changed = True
    if changed:
        _io.save_house_profiles(doc)
    _strip_attached_from_other_powerstations(ps_id, wanted)


def _scrub_battery_ids_from_scenarios(target: str) -> bool:
    """Remove ``target`` from all scenario ``battery_ids``; return True if changed."""
    from ui import house_config_io as _io

    doc = _io.load_backtesting_scenarios_raw()
    changed = False
    for scenario in doc.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        settings = scenario.get("settings")
        if not isinstance(settings, dict):
            continue
        raw_ids = settings.get("battery_ids")
        if not isinstance(raw_ids, list):
            continue
        before = [str(item or "").strip() for item in raw_ids if str(item or "").strip()]
        cleaned = [bat_id for bat_id in before if bat_id != target]
        if cleaned == before:
            continue
        settings["battery_ids"] = cleaned
        changed = True
    if changed:
        _io.save_backtesting_scenarios(doc)
    return changed


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


def _rewrite_shadow_battery_overlay(old_id: str, new_id: str) -> None:
    try:
        from runtime_store.shadow.ehal_overlay import read_overlay, write_overlay
        from runtime_store.shadow.mode import is_shadow_mode

        if not is_shadow_mode():
            return
        overlay = read_overlay()
        by_bat = overlay.get("battery_bindings")
        if not isinstance(by_bat, dict) or old_id not in by_bat:
            return
        from house_config.entity_id_lock import rewrite_ess_bindings_slug

        raw = by_bat.pop(old_id)
        by_bat[new_id] = rewrite_ess_bindings_slug(
            raw if isinstance(raw, dict) else {},
            old_id=old_id,
            new_id=new_id,
        )
        overlay["battery_bindings"] = by_bat
        write_overlay(overlay)
    except Exception:
        return


def upsert_battery(
    raw_spec: dict,
    *,
    stable_id: str = "",
    force_id_from_label: bool = False,
) -> str:
    """Upsert battery; return the persisted id (may rename when unlocking)."""
    from house_config.entity_id_lock import (
        ID_LOCKED_KEY,
        ID_PROVISIONAL_LABEL_KEY,
        resolve_id_on_save,
        rewrite_ess_bindings_slug,
    )
    from house_config.entity_resolution import normalize_battery
    from house_config.label_uniqueness import assert_unique_label

    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    old_id = str(stable_id or "").strip()
    existing = next(
        (
            item
            for item in batteries
            if isinstance(item, dict) and str(item.get("id", "")).strip() == old_id
        ),
        None,
    )
    taken = {str(item.get("id", "")) for item in batteries if item.get("id")}
    label = str(raw_spec.get("label", "")).strip()
    entity_id, id_locked, provisional = resolve_id_on_save(
        label=label,
        stable_id=old_id,
        existing=existing,
        taken=taken,
        provisional_from_ui=str(raw_spec.get(ID_PROVISIONAL_LABEL_KEY) or "").strip(),
        force_from_label=force_id_from_label,
    )
    assert_unique_label(label or entity_id, batteries, exclude_id=entity_id)
    # Planning form often sends empty ehal_bindings — keep disk bindings then.
    bindings_src = raw_spec.get("ehal_bindings")
    if (
        not (isinstance(bindings_src, dict) and any(str(v or "").strip() for v in bindings_src.values()))
        and isinstance(existing, dict)
        and isinstance(existing.get("ehal_bindings"), dict)
    ):
        bindings_src = existing.get("ehal_bindings")
    if old_id and old_id != entity_id:
        bindings_src = rewrite_ess_bindings_slug(
            bindings_src if isinstance(bindings_src, dict) else {},
            old_id=old_id,
            new_id=entity_id,
        )
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "battery_capacity_kwh": float(raw_spec["battery_capacity_kwh"]),
        "battery_max_charge_power_kw": float(
            raw_spec.get("battery_max_charge_power_kw", raw_spec.get("battery_max_power_kw"))
        ),
        "battery_max_discharge_power_kw": float(
            raw_spec.get(
                "battery_max_discharge_power_kw",
                raw_spec.get("battery_max_power_kw"),
            )
        ),
        "battery_efficiency": float(raw_spec["battery_efficiency"]),
        "battery_min_soc": float(raw_spec["battery_min_soc"]),
        "battery_max_soc": float(raw_spec["battery_max_soc"]),
        "threshold_power": float(raw_spec.get("threshold_power", 0.05)),
        "standby_power_kw": float(raw_spec.get("standby_power_kw", 0.0) or 0.0),
        "limits_from_live": bool(raw_spec.get("limits_from_live", False)),
    }
    if bindings_src is not None:
        raw_spec = dict(raw_spec)
        raw_spec["ehal_bindings"] = bindings_src
    if raw_spec.get("control") is not None:
        spec["control"] = raw_spec["control"]
    if raw_spec.get("type") is not None:
        spec["type"] = raw_spec["type"]
    if raw_spec.get("kind") is not None:
        spec["kind"] = raw_spec["kind"]
    for key in ("backing", "role", "attached_consumer_id", "attached_consumer_ids"):
        if raw_spec.get(key) is not None:
            spec[key] = raw_spec[key]
    existing_wear = None
    existing_control = None
    existing_type_fields: dict = {}
    lookup_id = old_id or entity_id
    if lookup_id:
        for item in batteries:
            if str(item.get("id", "")).strip() == lookup_id:
                existing_wear = item.get("battery_wear")
                existing_control = item.get("control")
                for key in (
                    "type",
                    "backing",
                    "role",
                    "attached_consumer_id",
                    "attached_consumer_ids",
                    "kind",
                ):
                    if key in item:
                        existing_type_fields[key] = item[key]
                break
    if "control" not in spec and existing_control is not None:
        spec["control"] = existing_control
    for key, value in existing_type_fields.items():
        spec.setdefault(key, value)
    if raw_spec.get("battery_wear") is not None:
        spec["battery_wear"] = raw_spec["battery_wear"]
    elif existing_wear is not None:
        spec["battery_wear"] = existing_wear
    else:
        spec["battery_wear"] = {"enabled": False}
    if raw_spec.get("ehal_bindings") is not None:
        spec["ehal_bindings"] = raw_spec["ehal_bindings"]
    from house_config.powerstation import apply_virtual_powerstation_inheritance

    siblings = [
        item
        for item in batteries
        if str(item.get("id", "")).strip() not in {entity_id, old_id}
    ]
    siblings.append(spec)
    spec = apply_virtual_powerstation_inheritance(spec, siblings)
    normalized = normalize_battery(spec, 0)
    # Persist split fields (drop legacy single max when both are present).
    save_spec = {
        "id": normalized["id"],
        "label": normalized["label"],
        "type": normalized.get("type", "house"),
        "battery_capacity_kwh": normalized["battery_capacity_kwh"],
        "battery_max_charge_power_kw": normalized["battery_max_charge_power_kw"],
        "battery_max_discharge_power_kw": normalized["battery_max_discharge_power_kw"],
        "battery_efficiency": normalized["battery_efficiency"],
        "battery_min_soc": normalized["battery_min_soc"],
        "battery_max_soc": normalized["battery_max_soc"],
        "threshold_power": normalized["threshold_power"],
        "standby_power_kw": normalized["standby_power_kw"],
        "control": normalized["control"],
        "kind": normalized.get("kind"),
        "limits_from_live": normalized["limits_from_live"],
        "battery_wear": normalized["battery_wear"]
        if normalized["battery_wear"] is not None
        else {"enabled": False},
        ID_LOCKED_KEY: id_locked,
    }
    if not id_locked and provisional:
        save_spec[ID_PROVISIONAL_LABEL_KEY] = provisional
    if normalized.get("type") == "powerstation":
        save_spec["backing"] = normalized["backing"]
        save_spec["role"] = normalized["role"]
        save_spec["attached_consumer_ids"] = list(
            normalized.get("attached_consumer_ids") or []
        )
        save_spec["attached_consumer_id"] = normalized.get("attached_consumer_id") or (
            save_spec["attached_consumer_ids"][0]
            if save_spec["attached_consumer_ids"]
            else ""
        )
    if normalized.get("ehal_bindings"):
        save_spec["ehal_bindings"] = normalized["ehal_bindings"]
    if old_id and old_id != entity_id:
        _rewrite_id_list_in_scenarios("battery_ids", old_id, entity_id)
        _rewrite_shadow_battery_overlay(old_id, entity_id)
    # Scrub before components save: reinit rejects Powerstations in battery_ids.
    if str(save_spec.get("type") or "") == "powerstation":
        _scrub_battery_ids_from_scenarios(entity_id)
        if old_id and old_id != entity_id:
            _scrub_battery_ids_from_scenarios(old_id)
    prev_attached: list[str] = []
    for item in batteries:
        if str(item.get("id", "")).strip() in {entity_id, old_id}:
            prev_attached = _attached_ids_from_battery(item)
            break
    batteries = [
        item
        for item in batteries
        if str(item.get("id", "")).strip() not in {entity_id, old_id}
    ]
    batteries.append(save_spec)
    data["batteries"] = batteries
    _save_components_document(data)
    if str(save_spec.get("type") or "") == "powerstation":
        new_attached = list(save_spec.get("attached_consumer_ids") or [])
        # Only push battery→consumer when the attached list itself changed;
        # otherwise auto-persist of inherited fields would detach consumers.
        if new_attached != prev_attached:
            sync_consumers_from_powerstation_attached(entity_id, new_attached)
    return entity_id

def delete_battery(entity_id: str) -> None:
    """Remove a battery from components.json and scrub scenario references."""
    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("Batterie-ID fehlt.")
    # Scrub first so components save → reinit does not see a dangling id.
    _scrub_battery_ids_from_scenarios(target)
    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    remaining = [item for item in batteries if str(item.get("id", "")).strip() != target]
    if len(remaining) == len(batteries):
        raise ValueError(f"Unbekannte Batterie '{target}'.")
    data["batteries"] = remaining
    _save_components_document(data)

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
