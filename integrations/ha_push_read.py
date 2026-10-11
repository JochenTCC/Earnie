"""HA Weg B push read helpers (inbox + qualified IDs; wire = canonical EHAL units)."""
from __future__ import annotations

from typing import Any

from ehal.ess_fields import ess_field_kind
from ehal.loxone_push_source import is_pushable_kind
from ehal.push_signals import pilot_id
from runtime_store.loxone_push_inbox import (
    STATE_READ_ERROR,
    read_push_counter,
    read_push_value,
)


def binding_entries(house: dict, components: dict) -> list[tuple[str, str, str, str, str]]:
    """``entity_kind, entity_id, consumer_type, field_key, entity_id_or_empty``."""
    entries: list[tuple[str, str, str, str, str]] = []
    for field, name in ((house.get("plant") or {}).get("ehal_bindings") or {}).items():
        entries.append(("plant", "plant", "", str(field), str(name)))
    profiles = house.get("profiles") or {}
    for profile in profiles.values() if isinstance(profiles, dict) else profiles:
        for consumer in profile.get("consumers", []):
            cid = str(consumer.get("id") or "")
            ctype = str(consumer.get("type") or "")
            for field, name in (consumer.get("ehal_bindings") or {}).items():
                entries.append(("consumer", cid, ctype, str(field), str(name)))
    for battery in components.get("batteries", []):
        bid = str(battery.get("id") or "")
        for field, name in (battery.get("ehal_bindings") or {}).items():
            entries.append(("battery", bid, "", str(field), str(name)))
    return entries


def push_read_qualified_ids(house: dict, components: dict) -> dict[str, str]:
    """``{binding_field_key: qualified_ehal_id}`` for activated pushable reads."""
    out: dict[str, str] = {}
    for kind, eid, ctype, field, _name in binding_entries(house, components):
        if not is_pushable_kind(field):
            continue
        qid = pilot_id(kind, eid, field, ctype)
        if qid:
            out[str(field)] = qid
    return out


def setpoint_qualified_ids(house: dict, components: dict) -> dict[str, str]:
    """``{binding_field_key: qualified_ehal_id}`` for activated ``set_*`` bindings."""
    out: dict[str, str] = {}
    for kind, eid, ctype, field, _name in binding_entries(house, components):
        if not str(field).startswith("set_"):
            continue
        qid = pilot_id(kind, eid, field, ctype)
        if qid:
            out[str(field)] = qid
    return out


def adapter_key_for_kind(
    entities: dict[str, str],
    kind: str,
) -> str | None:
    """Resolve a flat telemetry kind to an adapter entities key (incl. entity-scoped)."""
    target = str(kind or "").strip()
    if not target:
        return None
    if target in entities:
        return target
    for key in entities:
        if ess_field_kind(key) == target:
            return key
    return None


def read_push_ehal_value(
    qualified_id: str,
    *,
    sign: dict[str, str],
    adapter_field: str,
) -> float:
    """Read one push inbox value; apply ``sign`` only (wire is already EHAL units)."""
    value, state = read_push_value(qualified_id)
    if value is None:
        raise PushReadError(
            f"HA push read failed for {qualified_id!r} (field={adapter_field!r}, state={state})"
        )
    kind = ess_field_kind(adapter_field) or adapter_field
    if kind == "sens_ess_soc" or adapter_field == "sens_ess_soc":
        return float(value)
    mode = sign.get(adapter_field) or sign.get(kind)
    from integrations.ha_adapter import apply_sign

    return apply_sign(float(value), mode)


def read_push_energy_kwh(qualified_id: str) -> float | None:
    """Fresh cumulative kWh from inbox (no REST); ``None`` when missing/stale."""
    return read_push_counter(qualified_id)


class PushReadError(RuntimeError):
    """Required push missing/stale beyond last-known hold."""


def push_states_for_fields(
    field_to_qid: dict[str, str],
) -> dict[str, str]:
    """Best-effort push state labels for Live-Lesen (field key → inbox state)."""
    out: dict[str, str] = {}
    for field, qid in field_to_qid.items():
        _value, state = read_push_value(qid)
        if state:
            out[field] = state
    return out


def load_house_components_for_ha() -> tuple[dict, dict]:
    house: dict = {}
    components: dict = {}
    try:
        from house_config.ha_ehal_bindings import load_house_profiles_for_ha

        loaded = load_house_profiles_for_ha()
        if isinstance(loaded, dict):
            house = loaded
    except Exception:  # noqa: BLE001
        pass
    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if path:
            doc = load_components_document(path)
            if isinstance(doc, dict):
                components = doc
    except Exception:  # noqa: BLE001
        pass
    return house, components


def resolve_setpoint_qid(field: str, index: dict[str, str]) -> str:
    """Map adapter field / qualified id to publish key."""
    key = str(field or "").strip()
    if not key:
        return ""
    if key in index:
        return index[key]
    kind = ess_field_kind(key)
    if kind:
        for bind_key, qid in index.items():
            if ess_field_kind(bind_key) == kind:
                return qid
    return key if key.count(".") >= 2 else ""
