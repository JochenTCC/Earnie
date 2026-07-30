"""Loxone Energieflussmonitor / Zähler → Hausprofil consumer proposals (2.4.l)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from house_config.id_slug import slug_id

ROLE_GRID = "grid"
ROLE_PV = "pv"
ROLE_BATTERY = "battery"
ROLE_CONSUMER = "consumer"
ROLE_RESIDUAL = "residual"
ROLE_GROUP = "group"
ROLE_UNKNOWN = "unknown"

_PLANT_FIELDS = {
    ROLE_GRID: "sens_grid_power_active",
    ROLE_PV: "sens_pv_production_active",
    ROLE_BATTERY: "sens_ess_power",
}

_NODE_TO_ROLE = {
    "grid": ROLE_GRID,
    "production": ROLE_PV,
    "storage": ROLE_BATTERY,
    "load": ROLE_CONSUMER,
    "group": ROLE_GROUP,
}


@dataclass(frozen=True)
class EfmMeterCandidate:
    name: str
    uuid: str
    role: str
    node_type: str = ""
    details_type: str = ""
    power_address: str = ""
    csv_stem: str = ""
    plant_field: str = ""
    room: str = ""
    category: str = ""

    def as_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class ConsumerImportProposal:
    action: str  # create | match | skip_residual | skip_plant | skip_group
    name: str
    uuid: str
    consumer_id: str
    label: str
    power_address: str
    csv_stem: str
    matched_id: str = ""
    plant_field: str = ""

    def as_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}


def csv_stem_from_name(name: str) -> str:
    return slug_id(str(name or "").strip() or "zaehler")


def _room_cat_maps(doc: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    rooms: dict[str, str] = {}
    cats: dict[str, str] = {}
    for uid, meta in (doc.get("rooms") or {}).items():
        if isinstance(meta, dict):
            rooms[str(uid)] = str(meta.get("name") or "")
    for uid, meta in (doc.get("cats") or {}).items():
        if isinstance(meta, dict):
            cats[str(uid)] = str(meta.get("name") or "")
    return rooms, cats


def _role_from_node_type(node_type: str) -> str:
    return _NODE_TO_ROLE.get(str(node_type or "").strip().lower(), ROLE_UNKNOWN)


def _role_from_meter_meta(name: str, details_type: str) -> str:
    low = str(name or "").casefold()
    dtype = str(details_type or "").strip().lower()
    # EFM "Rest" may appear as Load in nodes — never treat as a consumer.
    if low in {"rest", "restlast"} or low.endswith(" rest"):
        return ROLE_RESIDUAL
    if dtype == "storage" or "batter" in low:
        return ROLE_BATTERY
    if "netz" in low or "grid" in low or dtype == "bidirectional":
        return ROLE_GRID
    if "pv" in low or "solar" in low or "produktion" in low or "erzeug" in low:
        return ROLE_PV
    return ROLE_CONSUMER


def _candidate_from_meter(
    *,
    name: str,
    uuid: str,
    role: str,
    node_type: str,
    details_type: str,
    room: str,
    category: str,
) -> EfmMeterCandidate:
    power = str(name or "").strip()
    plant = _PLANT_FIELDS.get(role, "")
    return EfmMeterCandidate(
        name=power,
        uuid=str(uuid or ""),
        role=role,
        node_type=str(node_type or ""),
        details_type=str(details_type or ""),
        power_address=power,
        csv_stem=csv_stem_from_name(power),
        plant_field=plant,
        room=room,
        category=category,
    )


def _resolve_node_role(
    *,
    node_type: str,
    name: str,
    details_type: str,
) -> str:
    role = _role_from_node_type(node_type)
    if role == ROLE_GROUP:
        return ROLE_GROUP
    meta_role = _role_from_meter_meta(name, details_type)
    if meta_role == ROLE_RESIDUAL:
        return ROLE_RESIDUAL
    if role == ROLE_UNKNOWN:
        return meta_role
    return role


def _walk_efm_nodes(
    nodes: list[Any],
    *,
    controls: dict[str, Any],
    rooms: dict[str, str],
    cats: dict[str, str],
    out: list[EfmMeterCandidate],
    seen: set[str],
) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("nodeType") or "")
        title = str(node.get("title") or "").strip()
        ctrl_uuid = str(node.get("ctrlUuid") or "").strip()
        children = node.get("nodes")
        if isinstance(children, list) and children:
            _walk_efm_nodes(
                children,
                controls=controls,
                rooms=rooms,
                cats=cats,
                out=out,
                seen=seen,
            )
        role_hint = _role_from_node_type(node_type)
        if role_hint == ROLE_GROUP:
            continue
        meta = controls.get(ctrl_uuid) if ctrl_uuid else None
        details_type = ""
        room = ""
        category = ""
        name = title
        if isinstance(meta, dict):
            name = str(meta.get("name") or title).strip() or title
            details = meta.get("details") if isinstance(meta.get("details"), dict) else {}
            details_type = str(details.get("type") or "")
            room = rooms.get(str(meta.get("room") or ""), "")
            category = cats.get(str(meta.get("cat") or ""), "")
        role = _resolve_node_role(
            node_type=node_type, name=name, details_type=details_type
        )
        key = ctrl_uuid or name
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(
            _candidate_from_meter(
                name=name,
                uuid=ctrl_uuid,
                role=role,
                node_type=node_type,
                details_type=details_type,
                room=room,
                category=category,
            )
        )


def _append_rest_subcontrols(
    efm: dict[str, Any],
    *,
    rooms: dict[str, str],
    cats: dict[str, str],
    out: list[EfmMeterCandidate],
    seen: set[str],
) -> None:
    sub = efm.get("subControls")
    if not isinstance(sub, dict):
        return
    for uid, meta in sub.items():
        if not isinstance(meta, dict):
            continue
        if str(meta.get("type") or "") != "Meter":
            continue
        name = str(meta.get("name") or "").strip() or "Rest"
        if uid in seen or name in seen:
            continue
        seen.add(str(uid))
        details = meta.get("details") if isinstance(meta.get("details"), dict) else {}
        out.append(
            _candidate_from_meter(
                name=name,
                uuid=str(uid),
                role=ROLE_RESIDUAL,
                node_type="Rest",
                details_type=str(details.get("type") or ""),
                room=rooms.get(str(meta.get("room") or ""), ""),
                category=cats.get(str(meta.get("cat") or ""), ""),
            )
        )


def _append_orphan_meters(
    controls: dict[str, Any],
    *,
    rooms: dict[str, str],
    cats: dict[str, str],
    out: list[EfmMeterCandidate],
    seen: set[str],
) -> None:
    for uid, meta in controls.items():
        if not isinstance(meta, dict) or str(meta.get("type") or "") != "Meter":
            continue
        if str(uid) in seen:
            continue
        name = str(meta.get("name") or "").strip()
        if not name or name in seen:
            continue
        details = meta.get("details") if isinstance(meta.get("details"), dict) else {}
        details_type = str(details.get("type") or "")
        role = _role_from_meter_meta(name, details_type)
        seen.add(str(uid))
        out.append(
            _candidate_from_meter(
                name=name,
                uuid=str(uid),
                role=role,
                node_type="",
                details_type=details_type,
                room=rooms.get(str(meta.get("room") or ""), ""),
                category=cats.get(str(meta.get("cat") or ""), ""),
            )
        )


def extract_efm_meters(doc: dict[str, Any]) -> list[EfmMeterCandidate]:
    """Extract Zähler/EFM meter candidates from a LoxAPP3 document."""
    if not isinstance(doc, dict):
        return []
    controls = doc.get("controls")
    if not isinstance(controls, dict):
        return []
    rooms, cats = _room_cat_maps(doc)
    out: list[EfmMeterCandidate] = []
    seen: set[str] = set()
    for meta in controls.values():
        if not isinstance(meta, dict) or str(meta.get("type") or "") != "EFM":
            continue
        details = meta.get("details") if isinstance(meta.get("details"), dict) else {}
        nodes = details.get("nodes")
        if isinstance(nodes, list):
            _walk_efm_nodes(
                nodes,
                controls=controls,
                rooms=rooms,
                cats=cats,
                out=out,
                seen=seen,
            )
        _append_rest_subcontrols(
            meta, rooms=rooms, cats=cats, out=out, seen=seen
        )
    _append_orphan_meters(controls, rooms=rooms, cats=cats, out=out, seen=seen)
    out.sort(key=lambda row: row.name.casefold())
    return out


def _match_existing(name: str, consumers: list[dict]) -> dict | None:
    key = name.casefold()
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        label = str(consumer.get("label") or "").strip()
        cid = str(consumer.get("id") or "").strip()
        if label.casefold() == key or cid.casefold() == key:
            return consumer
        # "Zähler X" ↔ "X"
        for prefix in ("zähler ", "zaehler "):
            if key.startswith(prefix) and label.casefold() == key[len(prefix) :]:
                return consumer
            if label.casefold().startswith(prefix) and key == label.casefold()[len(prefix) :]:
                return consumer
    return None


def propose_consumer_imports(
    candidates: list[EfmMeterCandidate],
    existing_consumers: list[dict],
) -> list[ConsumerImportProposal]:
    """Build HITL proposals: create/match consumers; plant/residual/group skipped."""
    taken = {
        str(c.get("id") or "").strip()
        for c in existing_consumers
        if isinstance(c, dict) and str(c.get("id") or "").strip()
    }
    proposals: list[ConsumerImportProposal] = []
    for cand in candidates:
        if cand.role == ROLE_RESIDUAL:
            action = "skip_residual"
        elif cand.role in _PLANT_FIELDS:
            action = "skip_plant"
        elif cand.role == ROLE_GROUP:
            action = "skip_group"
        else:
            action = "create"
        matched = _match_existing(cand.name, existing_consumers) if action == "create" else None
        if matched is not None:
            action = "match"
            cid = str(matched.get("id") or "").strip()
            label = str(matched.get("label") or cid).strip()
        else:
            label = cand.name
            cid = slug_id(label, existing=taken) if action == "create" else ""
            if cid:
                taken.add(cid)
        proposals.append(
            ConsumerImportProposal(
                action=action,
                name=cand.name,
                uuid=cand.uuid,
                consumer_id=cid,
                label=label,
                power_address=cand.power_address,
                csv_stem=cand.csv_stem,
                matched_id=str(matched.get("id") or "") if matched else "",
                plant_field=cand.plant_field,
            )
        )
    return proposals


def apply_consumer_imports(
    house_doc: dict,
    *,
    profile_id: str,
    selected: list[dict[str, Any]],
) -> dict:
    """Create/update generic consumers from HITL selections; return new house doc."""
    house = dict(house_doc)
    profiles = house.get("profiles")
    if not isinstance(profiles, dict) or not profile_id:
        raise ValueError("house profiles must be a dict with a live profile_id")
    profile = dict(profiles.get(profile_id) or {})
    consumers = [dict(c) for c in (profile.get("consumers") or []) if isinstance(c, dict)]
    by_id = {str(c.get("id") or ""): c for c in consumers if str(c.get("id") or "")}
    for row in selected:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "")
        if action not in {"create", "match"}:
            continue
        cid = str(row.get("consumer_id") or "").strip()
        label = str(row.get("label") or row.get("name") or cid).strip()
        if not cid or not label:
            continue
        bind_power = bool(row.get("bind_power", True))
        power = str(row.get("power_address") or "").strip()
        if action == "match" and cid in by_id:
            consumer = dict(by_id[cid])
        else:
            consumer = {
                "id": cid,
                "label": label,
                "type": "generic",
                "earnie_role": "known",
                "use_profile_csv": False,
                "nominal_power_kw": 1.0,
            }
        consumer["label"] = label
        if bind_power and power:
            bindings = (
                dict(consumer["ehal_bindings"])
                if isinstance(consumer.get("ehal_bindings"), dict)
                else {}
            )
            bindings["flex.power_name"] = power
            consumer["ehal_bindings"] = bindings
            # Do not invent enable_name / power_setpoint_name from Zähler.
        by_id[cid] = consumer
    profile["consumers"] = list(by_id.values())
    house["profiles"] = {**profiles, profile_id: profile}
    return house


def apply_plant_power_suggestions(
    house_doc: dict,
    *,
    selected: list[dict[str, Any]],
) -> dict:
    """Optionally set plant sens_* from grid/pv/battery Zähler names."""
    house = dict(house_doc)
    plant = dict(house.get("plant") or {}) if isinstance(house.get("plant"), dict) else {}
    bindings = dict(plant.get("ehal_bindings") or {})
    if not isinstance(plant.get("ehal_bindings"), dict):
        bindings = {}
    changed = False
    for row in selected:
        if not isinstance(row, dict):
            continue
        if str(row.get("action") or "") != "skip_plant":
            continue
        if not bool(row.get("bind_plant", False)):
            continue
        field = str(row.get("plant_field") or "").strip()
        power = str(row.get("power_address") or "").strip()
        if field and power:
            bindings[field] = power
            changed = True
    if changed:
        plant["ehal_bindings"] = bindings
        house["plant"] = plant
    return house
