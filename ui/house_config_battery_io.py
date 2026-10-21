"""Battery CRUD and Powerstation <-> consumer attachment sync (split from ``house_config_entities_io``).

Shared document helpers (``_load_components_document`` ...) are resolved through
``ui.house_config_entities_io`` at call time so patches on that module stay effective.
Names stay importable from ``ui.house_config_entities_io`` / ``ui.house_config_io``.
"""
from __future__ import annotations


def _ent():
    from ui import house_config_entities_io

    return house_config_entities_io


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
    data = _ent()._load_components_document()
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
        _ent()._save_components_document(data)


def _strip_attached_from_other_powerstations(
    powerstation_id: str, claimed: set[str]
) -> None:
    """Remove claimed consumer ids from sibling powerstation attached lists."""
    if not claimed:
        return
    data = _ent()._load_components_document()
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
        _ent()._save_components_document(data)


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


def _rewrite_shadow_battery_overlay(old_id: str, new_id: str) -> None:
    try:
        from runtime_store.shadow.ehal_overlay import read_overlay, write_overlay
        from runtime_store.shadow.mode import is_shadow_config_readonly

        if not is_shadow_config_readonly():
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


def _resolve_battery_bindings_src(
    raw_spec: dict, existing: dict | None, *, old_id: str, entity_id: str
) -> dict | None:
    """ehal_bindings to persist: planning form often sends empty ones — keep disk bindings then."""
    from house_config.entity_id_lock import rewrite_ess_bindings_slug

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
    return bindings_src


_BATTERY_FLOAT_SOURCES = (
    (
        "battery_max_charge_power_kw",
        ("battery_max_charge_power_kw", "battery_max_power_kw"),
    ),
    (
        "battery_max_discharge_power_kw",
        ("battery_max_discharge_power_kw", "battery_max_power_kw"),
    ),
    ("battery_efficiency", ("battery_efficiency",)),
    ("battery_min_soc", ("battery_min_soc",)),
    ("battery_max_soc", ("battery_max_soc",)),
)


def _battery_spec_from_raw(raw_spec: dict, *, entity_id: str, label: str) -> dict:
    """Spec fields taken from the raw form payload (no disk merge yet)."""
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "battery_capacity_kwh": float(raw_spec["battery_capacity_kwh"]),
        "threshold_power": float(raw_spec.get("threshold_power", 0.05)),
        "standby_power_kw": float(raw_spec.get("standby_power_kw", 0.0) or 0.0),
        "limits_from_live": bool(raw_spec.get("limits_from_live", False)),
    }
    # Virtual PS may omit electrical fields; inheritance fills them before normalize.
    for key, sources in _BATTERY_FLOAT_SOURCES:
        raw_val = None
        for src in sources:
            if raw_spec.get(src) is not None:
                raw_val = raw_spec.get(src)
                break
        if raw_val is not None:
            spec[key] = float(raw_val)
    if raw_spec.get("control") is not None:
        spec["control"] = raw_spec["control"]
    if raw_spec.get("regulates_on") is not None:
        spec["regulates_on"] = raw_spec["regulates_on"]
    if raw_spec.get("type") is not None:
        spec["type"] = raw_spec["type"]
    if raw_spec.get("inverter_id") is not None:
        inv_raw = str(raw_spec.get("inverter_id") or "").strip()
        if inv_raw:
            spec["inverter_id"] = inv_raw
    for key in ("backing", "role", "attached_consumer_id", "attached_consumer_ids"):
        if raw_spec.get(key) is not None:
            spec[key] = raw_spec[key]
    return spec


_EXISTING_TYPE_FIELD_KEYS = (
    "type",
    "backing",
    "role",
    "attached_consumer_id",
    "attached_consumer_ids",
    "inverter_id",
)


def _merge_existing_battery_fields(
    spec: dict, raw_spec: dict, batteries: list[dict], lookup_id: str
) -> None:
    """Fill control / regulates_on / type fields / wear from the stored battery."""
    existing_wear = None
    existing_control = None
    existing_regulates_on = None
    existing_type_fields: dict = {}
    if lookup_id:
        for item in batteries:
            if str(item.get("id", "")).strip() == lookup_id:
                existing_wear = item.get("battery_wear")
                existing_control = item.get("control")
                existing_regulates_on = item.get("regulates_on")
                for key in _EXISTING_TYPE_FIELD_KEYS:
                    if key in item:
                        existing_type_fields[key] = item[key]
                break
    if "control" not in spec and existing_control is not None:
        spec["control"] = existing_control
    if "regulates_on" not in spec and existing_regulates_on is not None:
        spec["regulates_on"] = existing_regulates_on
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


def _apply_battery_inverter_ownership(
    spec: dict, data: dict, *, entity_id: str, old_id: str
) -> dict:
    """Resolve the owned / referenced inverter of ``spec``; store the inverter list in ``data``."""
    from house_config.inverter_lifecycle import (
        drop_owned_inverters,
        ensure_owned_island_inverter,
        is_physical_powerstation,
        rebind_owned_by,
    )
    from house_config.powerstation import (
        apply_virtual_powerstation_inheritance,
        is_virtual_powerstation,
    )

    batteries = list(data.get("batteries") or [])
    siblings = [
        item
        for item in batteries
        if str(item.get("id", "")).strip() not in {entity_id, old_id}
    ]
    siblings.append(spec)
    spec = apply_virtual_powerstation_inheritance(spec, siblings)
    inverters = list(data.get("inverters") or [])
    renamed = bool(old_id and old_id != entity_id)
    if renamed:
        inverters = rebind_owned_by(
            inverters, old_battery_id=old_id, new_battery_id=entity_id
        )
    if is_virtual_powerstation(spec):
        spec.pop("inverter_id", None)
        inverters = drop_owned_inverters(inverters, battery_id=entity_id)
        if renamed:
            inverters = drop_owned_inverters(inverters, battery_id=old_id)
    elif is_physical_powerstation(spec):
        inverters, inv_id = ensure_owned_island_inverter(
            inverters,
            battery_id=entity_id,
            battery_label=str(spec.get("label") or entity_id),
        )
        spec["inverter_id"] = inv_id
    else:
        inv_id = str(spec.get("inverter_id") or "").strip()
        if not inv_id:
            raise ValueError(
                f"Batterie '{entity_id}': inverter_id fehlt "
                "(virtuelle Powerstations ausgenommen)."
            )
        inverters = drop_owned_inverters(
            inverters, battery_id=entity_id, keep_id=inv_id
        )
        if renamed:
            inverters = drop_owned_inverters(
                inverters, battery_id=old_id, keep_id=inv_id
            )
    data["inverters"] = inverters
    return spec


def _battery_save_spec(
    normalized: dict, *, id_locked: bool, provisional: str
) -> dict:
    """Persisted battery entry: split charge/discharge fields (legacy single max dropped)."""
    from house_config.entity_id_lock import ID_LOCKED_KEY, ID_PROVISIONAL_LABEL_KEY

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
        "limits_from_live": normalized["limits_from_live"],
        "battery_wear": normalized["battery_wear"]
        if normalized["battery_wear"] is not None
        else {"enabled": False},
        ID_LOCKED_KEY: id_locked,
    }
    if normalized.get("regulates_on") is not None:
        save_spec["regulates_on"] = normalized["regulates_on"]
    if not id_locked and provisional:
        save_spec[ID_PROVISIONAL_LABEL_KEY] = provisional
    inv_persist = str(normalized.get("inverter_id") or "").strip()
    if inv_persist:
        save_spec["inverter_id"] = inv_persist
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
    if isinstance(normalized.get("ehal_bindings"), dict):
        save_spec["ehal_bindings"] = normalized["ehal_bindings"]
    return save_spec


def _update_scenarios_for_battery_save(
    entity_id: str, old_id: str, *, is_powerstation: bool
) -> None:
    """Rewrite scenario battery ids on rename; scrub Powerstations from battery_ids."""
    renamed = bool(old_id and old_id != entity_id)
    if renamed:
        _ent()._rewrite_id_list_in_scenarios("battery_ids", old_id, entity_id)
        _rewrite_shadow_battery_overlay(old_id, entity_id)
    # Scrub before components save: reinit rejects Powerstations in battery_ids.
    if is_powerstation:
        _scrub_battery_ids_from_scenarios(entity_id)
        if renamed:
            _scrub_battery_ids_from_scenarios(old_id)


def _previous_attached_ids(batteries: list[dict], ids: set[str]) -> list[str]:
    """Attached consumer ids of the stored battery matching one of ``ids``."""
    for item in batteries:
        if str(item.get("id", "")).strip() in ids:
            return _attached_ids_from_battery(item)
    return []


def upsert_battery(
    raw_spec: dict,
    *,
    stable_id: str = "",
    force_id_from_label: bool = False,
) -> str:
    """Upsert battery; return the persisted id (may rename when unlocking)."""
    from house_config.entity_id_lock import ID_PROVISIONAL_LABEL_KEY, resolve_id_on_save
    from house_config.entity_resolution import normalize_battery
    from house_config.label_uniqueness import assert_unique_label

    data = _ent()._load_components_document()
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
    bindings_src = _resolve_battery_bindings_src(
        raw_spec, existing, old_id=old_id, entity_id=entity_id
    )
    spec = _battery_spec_from_raw(raw_spec, entity_id=entity_id, label=label)
    if bindings_src is not None:
        raw_spec = dict(raw_spec)
        raw_spec["ehal_bindings"] = bindings_src
    _merge_existing_battery_fields(spec, raw_spec, batteries, old_id or entity_id)
    spec = _apply_battery_inverter_ownership(
        spec, data, entity_id=entity_id, old_id=old_id
    )
    normalized = normalize_battery(spec, 0)
    save_spec = _battery_save_spec(
        normalized, id_locked=id_locked, provisional=provisional
    )
    from ehal.required_signals import grid_tied_house_battery_ids
    from house_config.required_signal_activation import activate_battery_required

    save_spec = activate_battery_required(
        save_spec,
        grid_tied_house=entity_id
        in grid_tied_house_battery_ids([save_spec], data.get("inverters")),
    )
    is_powerstation = str(save_spec.get("type") or "") == "powerstation"
    _update_scenarios_for_battery_save(
        entity_id, old_id, is_powerstation=is_powerstation
    )
    prev_attached = _previous_attached_ids(batteries, {entity_id, old_id})
    batteries = [
        item
        for item in batteries
        if str(item.get("id", "")).strip() not in {entity_id, old_id}
    ]
    batteries.append(save_spec)
    data["batteries"] = batteries
    _ent()._save_components_document(data)
    if is_powerstation:
        new_attached = list(save_spec.get("attached_consumer_ids") or [])
        # Only push battery→consumer when the attached list itself changed;
        # otherwise auto-persist of inherited fields would detach consumers.
        if new_attached != prev_attached:
            sync_consumers_from_powerstation_attached(entity_id, new_attached)
    return entity_id


def delete_battery(entity_id: str) -> None:
    """Remove a battery from components.json and scrub scenario references."""
    from house_config.inverter_lifecycle import (
        drop_owned_inverters,
        inverter_refs_blocking_delete,
    )

    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("Batterie-ID fehlt.")
    # Scrub first so components save → reinit does not see a dangling id.
    _scrub_battery_ids_from_scenarios(target)
    data = _ent()._load_components_document()
    batteries = list(data.get("batteries") or [])
    remaining = [item for item in batteries if str(item.get("id", "")).strip() != target]
    if len(remaining) == len(batteries):
        raise ValueError(f"Unbekannte Batterie '{target}'.")
    inverters = list(data.get("inverters") or [])
    owned_ids = [
        str(item.get("id") or "").strip()
        for item in inverters
        if isinstance(item, dict)
        and str(item.get("owned_by") or "").strip() == target
        and str(item.get("id") or "").strip()
    ]
    pv_systems = list(data.get("pv_systems") or [])
    for inv_id in owned_ids:
        refs = inverter_refs_blocking_delete(
            inverter_id=inv_id,
            batteries=remaining,
            pv_systems=pv_systems,
            exclude_battery_id=target,
        )
        if refs:
            raise ValueError(
                f"Batterie '{target}' hat integrierten Wechselrichter '{inv_id}', "
                "der noch referenziert wird: " + ", ".join(refs) + "."
            )
    data["batteries"] = remaining
    data["inverters"] = drop_owned_inverters(inverters, battery_id=target)
    _ent()._save_components_document(data)
