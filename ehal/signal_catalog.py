"""Catalog of EHAL signals for configured components (Binding P5b).

Role fields define what Earnie *can* use; ``ehal.required_signals`` marks
required kinds; activation = key present in ``ehal_bindings``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ehal.profiles import load_device_role
from ehal.push_signals import (
    pilot_id,
    title_from_qualified_id,
    vi_title_from_qualified_id,
)
from ehal.qualified_ids import EVCS_KINDS, field_kind, is_digital_id
from ehal.required_signals import (
    ComponentKind,
    binding_key_for_kind,
    required_binding_keys,
)
from house_config.battery_control import control_from_battery_params
from house_config.inverter import DEFAULT_INVERTER_CONTROL

Direction = Literal["read", "write"]


def _is_read(field: str) -> bool:
    return field_kind(field).startswith(("sens_", "get_"))


def _is_write(field: str) -> bool:
    return field_kind(field).startswith("set_")


def _group_for(entity_kind: str, entity_id: str) -> str:
    if entity_kind == "plant":
        return "Plant"
    if entity_kind == "battery":
        return f"Batterie_{entity_id}"
    if entity_kind == "inverter":
        return f"Wechselrichter_{entity_id}"
    if entity_kind == "pv_system":
        return f"PV_{entity_id}"
    if entity_id in ("pool_swimspa", "pool_filter"):
        return "Pool"
    if entity_id == "waermepumpe":
        return "Waermepumpe"
    if entity_id == "e_auto":
        return "EV"
    return "Verbraucher"


@dataclass(frozen=True)
class CatalogEntry:
    """One role-derived signal for a configured component instance."""

    component_kind: ComponentKind
    entity_id: str
    consumer_type: str
    binding_key: str
    ehal_id: str
    group: str
    direction: Direction
    digital: bool
    is_required: bool
    is_activated: bool


def _role_kinds(role_id: str) -> tuple[str, ...]:
    """Field kinds from a role template (skip capabilities / empty)."""
    role = load_device_role(role_id)
    kinds: list[str] = []
    seen: set[str] = set()
    for item in role.get("ehal_fields") or []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "capability":
            continue
        raw = str(item.get("field") or "").strip()
        if not raw:
            continue
        kind = field_kind(raw.replace("{hk_id}", "x"))
        if not kind or kind.startswith("supports_") or kind in seen:
            continue
        if not (kind.startswith(("sens_", "get_", "set_"))):
            continue
        seen.add(kind)
        kinds.append(kind)
    return tuple(kinds)


def _bindings_of(entity: dict[str, Any] | None) -> dict[str, Any]:
    raw = (entity or {}).get("ehal_bindings") if isinstance(entity, dict) else None
    return raw if isinstance(raw, dict) else {}


def _consumer_binding_key(entity_id: str, kind: str, consumer_type: str) -> str:
    """Storage key of a consumer kind, spelled as the mapping UI stores it."""
    from house_config.ehal_bindings import consumer_bare_stored_kinds

    if kind in consumer_bare_stored_kinds(consumer_type):
        return kind
    return binding_key_for_kind(
        component_kind="consumer",
        entity_id=entity_id,
        kind=kind,
        consumer_type=consumer_type,
    )


def _consumer_key_spellings(entity_id: str, kind: str, consumer_type: str) -> tuple[str, ...]:
    """Every key one consumer kind may be stored under (bare, qualified, legacy flex)."""
    from ehal.flex_fields import flex_ehal_slug
    from ehal.qualified_ids import qualified_consumer_id

    keys = [kind, qualified_consumer_id(entity_id, consumer_type, kind)]
    slug = flex_ehal_slug(entity_id)
    if slug:
        keys.append(f"flex.{slug}.{kind}")
    return tuple(dict.fromkeys(keys))


def _key_activated(
    bindings: dict[str, Any],
    binding_key: str,
    entity_id: str,
    *,
    component_kind: ComponentKind,
    consumer_type: str = "",
) -> bool:
    if binding_key in bindings:
        return True
    kind = field_kind(binding_key)
    if component_kind != "consumer" or not kind or not entity_id:
        return False
    return any(
        key in bindings for key in _consumer_key_spellings(entity_id, kind, consumer_type)
    )


def _entry(
    *,
    component_kind: ComponentKind,
    entity_id: str,
    kind: str,
    consumer_type: str,
    bindings: dict[str, Any],
    required: set[str],
) -> CatalogEntry | None:
    try:
        if component_kind == "consumer":
            binding_key = _consumer_binding_key(entity_id, kind, consumer_type)
        else:
            binding_key = binding_key_for_kind(
                component_kind=component_kind,
                entity_id=entity_id,
                kind=kind,
                consumer_type=consumer_type,
            )
    except ValueError:
        return None
    if _is_read(binding_key):
        direction: Direction = "read"
    elif _is_write(binding_key):
        direction = "write"
    else:
        return None
    ehal_id = pilot_id(component_kind, entity_id, binding_key, consumer_type)
    if not ehal_id:
        return None
    return CatalogEntry(
        component_kind=component_kind,
        entity_id=entity_id,
        consumer_type=consumer_type,
        binding_key=binding_key,
        ehal_id=ehal_id,
        group=_group_for(component_kind, entity_id),
        direction=direction,
        digital=is_digital_id(ehal_id),
        is_required=binding_key in required,
        is_activated=_key_activated(
            bindings,
            binding_key,
            entity_id,
            component_kind=component_kind,
            consumer_type=consumer_type,
        ),
    )


def _with_live_reads(role_kinds: tuple[str, ...], live_kinds: tuple[str, ...]) -> tuple[str, ...]:
    """Role kinds plus every kind Live-Lesen reads, so the export covers the same signals."""
    return tuple(dict.fromkeys(role_kinds + live_kinds))


def _plant_kinds() -> tuple[str, ...]:
    # Plant wire: grid role (plant PV retired; PV lives on inv.*/pv.*) + house-wide reads
    # (outside temperature, absent mode, slot-Ist energy counters) from the Live-Lesen table.
    from integrations.ehal_debug_fields import PLANT_HOUSE_LIVE_READ_FIELDS

    return _with_live_reads(_role_kinds("grid"), PLANT_HOUSE_LIVE_READ_FIELDS)


def _consumer_kinds(consumer: dict[str, Any], consumer_type: str) -> tuple[str, ...]:
    from integrations.ehal_debug_mapping import consumer_live_read_kinds

    return _with_live_reads(
        _role_kinds(_consumer_role_id(consumer_type)), consumer_live_read_kinds(consumer)
    )


def _consumer_role_id(consumer_type: str) -> str:
    ctype = str(consumer_type or "").strip().lower()
    if ctype == "ev":
        return "evcs"
    if ctype == "thermal_annual":
        return "heatpump"
    return "consumer"


def _add_kind_entries(
    add,
    *,
    component_kind: ComponentKind,
    entity_id: str,
    kinds: tuple[str, ...],
    consumer_type: str,
    bindings: dict[str, Any],
    required: set[str],
) -> None:
    for kind in kinds:
        add(
            _entry(
                component_kind=component_kind,
                entity_id=entity_id,
                kind=kind,
                consumer_type=consumer_type,
                bindings=bindings,
                required=required,
            )
        )


def _entity_id_of(item: Any) -> str:
    """Stripped ``id`` of a component dict; empty for non-dicts or a missing id."""
    if not isinstance(item, dict):
        return ""
    return str(item.get("id") or "").strip()


def _add_plant_entries(house: dict, add) -> None:
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    _add_kind_entries(
        add,
        component_kind="plant",
        entity_id="plant",
        kinds=_plant_kinds(),
        consumer_type="",
        bindings=_bindings_of(plant),
        required=set(required_binding_keys(component_kind="plant")),
    )


def _add_battery_entries(components: dict, add) -> None:
    from ehal.required_signals import grid_tied_house_battery_ids

    grid_tied = grid_tied_house_battery_ids(
        components.get("batteries"), components.get("inverters")
    )
    for battery in components.get("batteries") or []:
        bid = _entity_id_of(battery)
        if not bid:
            continue
        required = set(
            required_binding_keys(
                component_kind="battery",
                entity_id=bid,
                control=control_from_battery_params(battery),
                grid_tied_house=bid in grid_tied,
            )
        )
        _add_kind_entries(
            add,
            component_kind="battery",
            entity_id=bid,
            kinds=_role_kinds("ess"),
            consumer_type="",
            bindings=_bindings_of(battery),
            required=required,
        )


def _add_inverter_entries(components: dict, add) -> None:
    from ehal.required_signals import inverter_has_attached_pv

    pv_systems = list(components.get("pv_systems") or [])
    for inverter in components.get("inverters") or []:
        iid = _entity_id_of(inverter)
        if not iid:
            continue
        control = str(inverter.get("control") or DEFAULT_INVERTER_CONTROL).strip()
        required = set(
            required_binding_keys(
                component_kind="inverter",
                entity_id=iid,
                control=control,
                has_attached_pv=inverter_has_attached_pv(iid, pv_systems),
            )
        )
        _add_kind_entries(
            add,
            component_kind="inverter",
            entity_id=iid,
            kinds=_role_kinds("inverter"),
            consumer_type="",
            bindings=_bindings_of(inverter),
            required=required,
        )


def _add_pv_entries(components: dict, add) -> None:
    for pv in components.get("pv_systems") or []:
        pid = _entity_id_of(pv)
        if not pid:
            continue
        _add_kind_entries(
            add,
            component_kind="pv_system",
            entity_id=pid,
            kinds=_role_kinds("pv"),
            consumer_type="",
            bindings=_bindings_of(pv),
            required=set(required_binding_keys(component_kind="pv_system", entity_id=pid)),
        )


def _add_profile_consumer_entries(profile: dict, add) -> None:
    for consumer in profile.get("consumers") or []:
        cid = _entity_id_of(consumer)
        if not cid:
            continue
        ctype = str(consumer.get("type") or "").strip()
        required = set(
            required_binding_keys(
                component_kind="consumer",
                entity_id=cid,
                consumer_type=ctype,
            )
        )
        bindings = _bindings_of(consumer)
        kinds = _consumer_kinds(consumer, ctype)
        if ctype == "ev" and _ev_charger_is_wallbox(consumer):
            # The charger side is the wallbox's (``evcs.<Wallbox>.*``), listed below.
            kinds = tuple(k for k in kinds if k not in EVCS_KINDS)
        _add_kind_entries(
            add,
            component_kind="consumer",
            entity_id=cid,
            kinds=kinds,
            consumer_type=ctype,
            bindings=bindings,
            required=required,
        )


def _add_consumer_entries(house: dict, components: dict, add) -> None:
    profiles = house.get("profiles") or {}
    profile_iter = (
        profiles.values() if isinstance(profiles, dict) else profiles
    )
    for profile in profile_iter:
        if not isinstance(profile, dict):
            continue
        _add_profile_consumer_entries(profile, add)
        _add_rod_entries(profile, components, add)


def iter_catalog_entries(house: dict, components: dict) -> list[CatalogEntry]:
    """All role signals for configured plant / batteries / inverters / PV / consumers."""
    out: list[CatalogEntry] = []
    # Bare consumer keys (heat / pool kinds) repeat across consumers: key by entity too.
    seen: set[tuple[str, str, str]] = set()

    def _add(entry: CatalogEntry | None) -> None:
        if entry is None:
            return
        ident = (entry.component_kind, entry.entity_id, entry.binding_key)
        if ident in seen:
            return
        seen.add(ident)
        out.append(entry)

    _add_plant_entries(house, _add)
    _add_battery_entries(components, _add)
    _add_inverter_entries(components, _add)
    _add_pv_entries(components, _add)
    _add_consumer_entries(house, components, _add)
    _add_wallbox_entries(house, components, _add)
    return out


def _ev_charger_is_wallbox(consumer: dict[str, Any]) -> bool:
    """True for an EV with a wallbox assignment (dm6): it has no charger signals of its own."""
    from house_config.wallboxes import WALLBOX_ASSIGNMENT_KEY

    return isinstance(consumer.get(WALLBOX_ASSIGNMENT_KEY), dict)


def _wallbox_kinds() -> tuple[str, ...]:
    """Charger kinds of a wallbox: role order first, then the rest of ``EVCS_KINDS``."""
    role = [k for k in _role_kinds("evcs") if k in EVCS_KINDS]
    return tuple(dict.fromkeys(role + sorted(EVCS_KINDS)))


def _wallbox_use(house: dict) -> tuple[set[str], set[str]]:
    """(wallboxes an EV of an active profile uses, those of them open to dynamic EVs)."""
    from house_config.wallboxes import (
        assigned_wallbox_id,
        dynamic_wallbox_ids,
        iter_house_evs,
    )

    used: set[str] = set()
    dynamic: set[str] = set()
    profiles = house.get("profiles") or {}
    for profile in profiles.values() if isinstance(profiles, dict) else profiles:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if isinstance(consumer, dict) and str(consumer.get("type") or "") == "ev":
                fixed = assigned_wallbox_id(consumer)
                if fixed:
                    used.add(fixed)
    for _pid, ev in iter_house_evs(house):
        dynamic.update(i for i in dynamic_wallbox_ids(ev) if i)
    return used | dynamic, dynamic


def _add_wallbox_entries(house: dict, components: dict, add) -> None:
    """Charger signals ``evcs.<Wallbox>.*`` of every wallbox an EV uses.

    Same IDs as the inbox index and the write path (``push_signals``): the Kennung is the
    wallbox, not the EV. The stecker signal is required where a dynamic EV may plug in.
    """
    from ehal.qualified_ids import qualified_charger_id
    from ehal.required_signals import required_kinds_for_consumer

    used, dynamic = _wallbox_use(house)
    for wallbox in components.get("wallboxes") or []:
        if not isinstance(wallbox, dict):
            continue
        wid = str(wallbox.get("id") or "").strip()
        if not wid or wid not in used:
            continue
        required = set(required_kinds_for_consumer("ev"))
        if wid in dynamic:
            required.add("sens_evcs_connected")
        active = {field_kind(str(key)) for key in _bindings_of(wallbox)}
        for kind in _wallbox_kinds():
            key = qualified_charger_id(wid, kind)
            add(
                CatalogEntry(
                    component_kind="wallbox",
                    entity_id=wid,
                    consumer_type="ev",
                    binding_key=key,
                    ehal_id=key,
                    group=_group_for("consumer", wid),
                    direction="read" if _is_read(kind) else "write",
                    digital=is_digital_id(key),
                    is_required=kind in required,
                    is_activated=kind in active,
                )
            )


def _add_rod_entries(profile: dict, components: dict, add) -> None:
    """Rod signals: an entity of its own, never required (Live just does not plan it)."""
    from house_config.heating_rod_bindings import ROD_KINDS, rod_mapping_entities

    for rod in rod_mapping_entities(profile.get("consumers") or [], components):
        for kind in ROD_KINDS:
            add(
                _entry(
                    component_kind="consumer",
                    entity_id=rod["id"],
                    kind=kind,
                    consumer_type=rod["type"],
                    bindings=rod["ehal_bindings"],
                    required=set(),
                )
            )


def _set_rod_activation(consumer: dict, key: str, activated: bool) -> dict:
    from house_config.heating_rod_bindings import ROD_BINDINGS_KEY

    out = dict(consumer)
    bindings = dict(out.get(ROD_BINDINGS_KEY) or {})
    if activated:
        bindings.setdefault(key, "")
    else:
        bindings.pop(key, None)
    if bindings:
        out[ROD_BINDINGS_KEY] = bindings
    else:
        out.pop(ROD_BINDINGS_KEY, None)
    return out


def _toggle_binding(bindings: dict[str, Any], key: str, activated: bool) -> None:
    if activated:
        bindings.setdefault(key, "")
    else:
        bindings.pop(key, None)


def _set_plant_activation(house_out: dict, key: str, activated: bool) -> None:
    plant = dict(house_out.get("plant") or {})
    bindings = dict(plant.get("ehal_bindings") or {})
    _toggle_binding(bindings, key, activated)
    plant["ehal_bindings"] = bindings
    house_out["plant"] = plant


def _consumer_with_activation(
    consumer: dict, entity_id: str, key: str, activated: bool, consumer_type: str
) -> dict:
    """The consumer with ``key`` (any spelling of its kind) added or removed."""
    c = dict(consumer)
    bindings = dict(c.get("ehal_bindings") or {})
    ctype = str(c.get("type") or consumer_type or "").strip()
    peers = _consumer_key_spellings(entity_id, field_kind(key), ctype)
    if activated:
        # Already stored under another spelling: keep that one, add none.
        if not any(peer in bindings for peer in (key, *peers)):
            bindings[key] = ""
    else:
        for peer in (key, *peers):
            bindings.pop(peer, None)
    c["ehal_bindings"] = bindings
    return c


def _profile_consumers_with_activation(
    profile: dict, entity_id: str, key: str, activated: bool, consumer_type: str
) -> list:
    from house_config.heating_rod_bindings import rod_kennung

    consumers = []
    for consumer in profile.get("consumers") or []:
        if not isinstance(consumer, dict):
            consumers.append(consumer)
        elif (
            consumer.get("type") == "thermal_annual"
            and rod_kennung(str(consumer.get("id") or "").strip()) == entity_id
        ):
            consumers.append(_set_rod_activation(consumer, key, activated))
        elif str(consumer.get("id") or "").strip() != entity_id:
            consumers.append(consumer)
        else:
            consumers.append(
                _consumer_with_activation(consumer, entity_id, key, activated, consumer_type)
            )
    return consumers


def _set_consumer_activation(
    house_out: dict, entity_id: str, key: str, activated: bool, consumer_type: str
) -> None:
    profiles = house_out.get("profiles")
    if not isinstance(profiles, dict):
        return
    new_profiles: dict[str, Any] = {}
    for pname, profile in profiles.items():
        if not isinstance(profile, dict):
            new_profiles[pname] = profile
            continue
        consumers = _profile_consumers_with_activation(
            profile, entity_id, key, activated, consumer_type
        )
        new_profiles[pname] = {**profile, "consumers": consumers}
    house_out["profiles"] = new_profiles


def _row_with_activation(item: dict, component_kind: str, key: str, activated: bool) -> dict:
    row = dict(item)
    bindings = dict(row.get("ehal_bindings") or {})
    if component_kind == "wallbox":
        # A wallbox stores a kind bare or qualified: one kind, one key.
        same_kind = [k for k in bindings if field_kind(str(k)) == field_kind(key)]
        if activated and not same_kind:
            bindings[key] = ""
        elif not activated:
            for peer in same_kind:
                bindings.pop(peer)
    else:
        _toggle_binding(bindings, key, activated)
    row["ehal_bindings"] = bindings
    return row


_COMPONENT_LIST_KEYS: dict[str, str] = {
    "battery": "batteries",
    "inverter": "inverters",
    "pv_system": "pv_systems",
    "wallbox": "wallboxes",
}


def _set_component_activation(
    comp_out: dict, component_kind: str, entity_id: str, key: str, activated: bool
) -> None:
    list_key = _COMPONENT_LIST_KEYS.get(component_kind)
    if not list_key:
        raise ValueError(f"unsupported component_kind {component_kind!r}")
    items = []
    for item in comp_out.get(list_key) or []:
        if not isinstance(item, dict) or _entity_id_of(item) != entity_id:
            items.append(item)
            continue
        items.append(_row_with_activation(item, component_kind, key, activated))
    comp_out[list_key] = items


def set_binding_activation(
    house: dict,
    components: dict,
    *,
    component_kind: ComponentKind,
    entity_id: str,
    binding_key: str,
    activated: bool,
    consumer_type: str = "",
    is_required: bool = False,
) -> tuple[dict, dict]:
    """Add or remove a binding key. Required keys cannot be deactivated."""
    if is_required and not activated:
        raise ValueError(f"required signal cannot be deactivated: {binding_key}")
    key = str(binding_key or "").strip()
    if not key:
        raise ValueError("binding_key must be non-empty")

    house_out = dict(house) if isinstance(house, dict) else {}
    comp_out = dict(components) if isinstance(components, dict) else {}

    if component_kind == "plant":
        _set_plant_activation(house_out, key, activated)
    elif component_kind == "consumer":
        _set_consumer_activation(house_out, entity_id, key, activated, consumer_type)
    else:
        _set_component_activation(comp_out, component_kind, entity_id, key, activated)
    return house_out, comp_out


def catalog_to_signals(
    entries: list[CatalogEntry],
    *,
    activated_only: bool,
) -> tuple[list, list]:
    """Build (read, write) ``Signal`` lists for VO/VI export from catalog."""
    from ehal.push_signals import Signal, is_valid_write_ehal_id
    from runtime_store.loxone_push_parse import is_valid_ehal_id

    reads: list[Signal] = []
    writes: list[Signal] = []
    used_titles: set[str] = set()
    for entry in entries:
        if activated_only and not entry.is_activated:
            continue
        accepted = is_valid_ehal_id if entry.direction == "read" else is_valid_write_ehal_id
        if not accepted(entry.ehal_id):
            # Same check as the inbox and the write path: a template with this ID would
            # be wired in the hub and never arrive.
            raise ValueError(
                f"Kennung '{entry.entity_id}' ergibt die EHAL-ID '{entry.ehal_id}', die "
                "Earnie nicht annimmt: erlaubt sind a–z, 0–9 und _ (höchstens 64 Zeichen). "
                "Bitte die Kennung im Hauskonfigurator ändern."
            )
        title_fn = (
            title_from_qualified_id
            if entry.direction == "read"
            else vi_title_from_qualified_id
        )
        base = title_fn(entry.ehal_id)
        title = base
        suffix = 2
        while title in used_titles:
            title, suffix = f"{base}_{suffix}", suffix + 1
        used_titles.add(title)
        sig = Signal(
            group=entry.group,
            ehal_id=entry.ehal_id,
            old_name=entry.ehal_id,
            title=title,
            digital=entry.digital,
        )
        if entry.direction == "read":
            reads.append(sig)
        else:
            writes.append(sig)
    return reads, writes
