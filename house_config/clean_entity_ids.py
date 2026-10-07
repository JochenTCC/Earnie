"""Batch-clean dirty battery/PV ids from Bezeichnung (offline earnie_env)."""
from __future__ import annotations

from dataclasses import dataclass

from house_config.entity_id_lock import (
    ID_LOCKED_KEY,
    ID_PROVISIONAL_LABEL_KEY,
    rewrite_ess_bindings_slug,
)
from house_config.id_slug import slug_id


@dataclass(frozen=True)
class IdRename:
    kind: str  # "battery" | "pv"
    old_id: str
    new_id: str
    label: str


def looks_like_copy_id(entity_id: str) -> bool:
    """True for …_copy / …_copy_N style ids from the UI clone flow."""
    return "_copy" in str(entity_id or "")


def _entity_label(item: dict) -> str:
    eid = str(item.get("id") or "").strip()
    return str(item.get("label") or eid).strip() or eid


def _plan_list_renames(
    items: list,
    *,
    kind: str,
    only_copy: bool,
) -> list[IdRename]:
    entities = [item for item in items if isinstance(item, dict)]
    taken = {
        str(item.get("id") or "").strip()
        for item in entities
        if str(item.get("id") or "").strip()
    }
    renames: list[IdRename] = []
    for item in entities:
        old_id = str(item.get("id") or "").strip()
        if not old_id:
            continue
        if only_copy and not looks_like_copy_id(old_id):
            continue
        label = _entity_label(item)
        candidates = set(taken)
        candidates.discard(old_id)
        new_id = slug_id(label or old_id, existing=candidates)
        if new_id == old_id:
            continue
        renames.append(IdRename(kind=kind, old_id=old_id, new_id=new_id, label=label))
        taken.discard(old_id)
        taken.add(new_id)
    return renames


def _rewrite_id_list(raw_ids: object, mapping: dict[str, str]) -> list[str] | None:
    if not isinstance(raw_ids, list):
        return None
    before = [str(item or "").strip() for item in raw_ids if str(item or "").strip()]
    after: list[str] = []
    seen: set[str] = set()
    for item in before:
        mapped = mapping.get(item, item)
        if mapped in seen:
            continue
        seen.add(mapped)
        after.append(mapped)
    return after if after != before else None


def _rewrite_scenarios(scenarios: dict, mapping: dict[str, str], *, list_key: str) -> bool:
    changed = False
    for scenario in scenarios.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        settings = scenario.get("settings")
        if not isinstance(settings, dict):
            continue
        rewritten = _rewrite_id_list(settings.get(list_key), mapping)
        if rewritten is not None:
            settings[list_key] = rewritten
            changed = True
        # Legacy singular keys (if still present on dirty packs).
        singular = list_key.removesuffix("s")  # battery_id / pv_system_id
        if singular in settings and isinstance(settings.get(singular), str):
            old = str(settings.get(singular) or "").strip()
            if old in mapping:
                settings[singular] = mapping[old]
                changed = True
    return changed


def _rewrite_house_powerstation_refs(house: dict, mapping: dict[str, str]) -> bool:
    changed = False
    for profile in house.get("profiles") or []:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("flexible_consumers") or []:
            if not isinstance(consumer, dict):
                continue
            rec = consumer.get("appliance_recommendation")
            if not isinstance(rec, dict):
                continue
            old = str(rec.get("powerstation_id") or "").strip()
            if old in mapping:
                rec["powerstation_id"] = mapping[old]
                changed = True
    return changed


def _apply_battery_renames(batteries: list, renames: list[IdRename]) -> None:
    by_old = {r.old_id: r for r in renames if r.kind == "battery"}
    for item in batteries:
        if not isinstance(item, dict):
            continue
        old_id = str(item.get("id") or "").strip()
        rename = by_old.get(old_id)
        if rename is None:
            continue
        item["id"] = rename.new_id
        item[ID_LOCKED_KEY] = True
        item.pop(ID_PROVISIONAL_LABEL_KEY, None)
        bindings = item.get("ehal_bindings")
        if isinstance(bindings, dict) and bindings:
            item["ehal_bindings"] = rewrite_ess_bindings_slug(
                bindings, old_id=old_id, new_id=rename.new_id
            )


def _apply_pv_renames(systems: list, renames: list[IdRename]) -> None:
    by_old = {r.old_id: r for r in renames if r.kind == "pv"}
    for item in systems:
        if not isinstance(item, dict):
            continue
        old_id = str(item.get("id") or "").strip()
        rename = by_old.get(old_id)
        if rename is None:
            continue
        item["id"] = rename.new_id
        item[ID_LOCKED_KEY] = True
        item.pop(ID_PROVISIONAL_LABEL_KEY, None)


def plan_clean_entity_ids(
    components: dict,
    *,
    only_copy: bool = False,
) -> list[IdRename]:
    """Return planned renames (batteries then PV); does not mutate."""
    batteries = list(components.get("batteries") or [])
    pv_systems = list(components.get("pv_systems") or [])
    return [
        *_plan_list_renames(batteries, kind="battery", only_copy=only_copy),
        *_plan_list_renames(pv_systems, kind="pv", only_copy=only_copy),
    ]


def apply_clean_entity_ids(
    components: dict,
    scenarios: dict | None = None,
    house_profiles: dict | None = None,
    *,
    only_copy: bool = False,
) -> tuple[dict, dict | None, dict | None, list[IdRename]]:
    """Apply id cleanups in-memory; return updated docs + rename list."""
    import copy

    comp_out = copy.deepcopy(components)
    scen_out = copy.deepcopy(scenarios) if isinstance(scenarios, dict) else None
    house_out = copy.deepcopy(house_profiles) if isinstance(house_profiles, dict) else None

    renames = plan_clean_entity_ids(comp_out, only_copy=only_copy)
    if not renames:
        return comp_out, scen_out, house_out, []

    batteries = list(comp_out.get("batteries") or [])
    pv_systems = list(comp_out.get("pv_systems") or [])
    _apply_battery_renames(batteries, renames)
    _apply_pv_renames(pv_systems, renames)
    comp_out["batteries"] = batteries
    comp_out["pv_systems"] = pv_systems

    bat_map = {r.old_id: r.new_id for r in renames if r.kind == "battery"}
    pv_map = {r.old_id: r.new_id for r in renames if r.kind == "pv"}
    if scen_out is not None:
        if bat_map:
            _rewrite_scenarios(scen_out, bat_map, list_key="battery_ids")
        if pv_map:
            _rewrite_scenarios(scen_out, pv_map, list_key="pv_system_ids")
    if house_out is not None and bat_map:
        _rewrite_house_powerstation_refs(house_out, bat_map)

    return comp_out, scen_out, house_out, renames
