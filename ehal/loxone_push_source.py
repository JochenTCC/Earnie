"""Per-entity push vs poll source switch for the Loxone VO push migration.

Config: ``ehal.loxone_push.entities`` — list of entity keys that read from the
push inbox instead of Merker poll. Keys: ``plant``, ``battery:<id>``,
``consumer:<id>``. Default (missing/empty) = all poll.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ehal.push_signals import pilot_id
from ehal.qualified_ids import field_kind

logger = logging.getLogger(__name__)

# AlarmClock / SpecialState10 and meter ``/all`` energy stay on poll forever.
NEVER_PUSH_KINDS = frozenset({"get_evcs_ready_by_time"})
_ENERGY_KIND_SUFFIX = "_energy"


@dataclass(frozen=True)
class MerkerBinding:
    """One Merker name mapped to a pushable EHAL ID and its entity key."""

    merker: str
    ehal_id: str
    entity_key: str
    kind: str


def entity_key(entity_kind: str, entity_id: str) -> str:
    """Stable config key for the source switch (``plant``, ``battery:…``, ``consumer:…``)."""
    kind = str(entity_kind or "").strip()
    eid = str(entity_id or "").strip()
    if kind == "plant":
        return "plant"
    if kind == "battery":
        return f"battery:{eid}"
    if kind == "consumer":
        return f"consumer:{eid}"
    raise ValueError(f"unknown entity kind: {entity_kind!r}")


def parse_push_entities(raw: object) -> frozenset[str]:
    """Parse ``ehal.loxone_push.entities`` into a frozenset of entity keys."""
    if not isinstance(raw, list):
        return frozenset()
    keys: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if text:
            keys.add(text)
    return frozenset(keys)


def load_push_entities_from_config(raw_config: dict | None = None) -> frozenset[str]:
    """Read push entity keys from a config dict or the live ``config.json``."""
    if raw_config is None:
        import json

        from runtime_store.persist_paths import resolve_config_json_path

        path = resolve_config_json_path()
        try:
            with open(path, encoding="utf-8") as handle:
                raw_config = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            raw_config = {}
    ehal = raw_config.get("ehal") if isinstance(raw_config, dict) else None
    push = ehal.get("loxone_push") if isinstance(ehal, dict) else None
    entities = push.get("entities") if isinstance(push, dict) else None
    return parse_push_entities(entities)


def is_pushable_kind(kind: str) -> bool:
    """False for fields that never go through the VO push path."""
    k = field_kind(kind)
    if k in NEVER_PUSH_KINDS:
        return False
    if k.endswith(_ENERGY_KIND_SUFFIX):
        return False
    return k.startswith(("sens_", "get_"))


def merker_bindings_from_docs(house: dict, components: dict) -> list[MerkerBinding]:
    """All pushable Merker → EHAL ID bindings from saved house/components docs."""
    out: list[MerkerBinding] = []
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

    for kind, eid, ctype, field, name in entries:
        merker = str(name or "").strip()
        if not merker or not is_pushable_kind(field):
            continue
        ehal_id = pilot_id(kind, eid, field, ctype)
        if ehal_id is None:
            continue
        out.append(
            MerkerBinding(
                merker=merker,
                ehal_id=ehal_id,
                entity_key=entity_key(kind, eid),
                kind=field_kind(field),
            )
        )
    return out


def build_merker_index(
    house: dict, components: dict
) -> dict[str, MerkerBinding]:
    """``{merker_name: MerkerBinding}`` (last wins on duplicate Merker names)."""
    index: dict[str, MerkerBinding] = {}
    for binding in merker_bindings_from_docs(house, components):
        index[binding.merker] = binding
    return index


_index_cache: dict[str, MerkerBinding] | None = None
_push_entities_cache: frozenset[str] | None = None


def clear_source_caches() -> None:
    """Reset lazy caches (tests / after config reload)."""
    global _index_cache, _push_entities_cache
    _index_cache = None
    _push_entities_cache = None


def _load_house_components() -> tuple[dict, dict]:
    from house_config.components_store import load_components_document
    from house_config.profiles_store import load_house_profiles_document
    from runtime_store.persist_paths import (
        resolve_components_json_path,
        resolve_house_profiles_json_path,
    )

    house = load_house_profiles_document(resolve_house_profiles_json_path())
    components = load_components_document(resolve_components_json_path())
    return house if isinstance(house, dict) else {}, components if isinstance(components, dict) else {}


def get_merker_index() -> dict[str, MerkerBinding]:
    global _index_cache
    if _index_cache is None:
        try:
            house, components = _load_house_components()
            _index_cache = build_merker_index(house, components)
        except Exception:  # noqa: BLE001 — poll path must keep working
            logger.exception("loxone push: failed to build Merker index")
            _index_cache = {}
    return _index_cache


def get_push_entities() -> frozenset[str]:
    global _push_entities_cache
    if _push_entities_cache is None:
        try:
            _push_entities_cache = load_push_entities_from_config()
        except Exception:  # noqa: BLE001
            logger.exception("loxone push: failed to load push entities")
            _push_entities_cache = frozenset()
    return _push_entities_cache


def source_for_merker(merker: str) -> str:
    """Return ``push`` or ``poll`` for a Merker name (AlarmClock/energy always poll)."""
    name = str(merker or "").strip()
    if not name:
        return "poll"
    binding = get_merker_index().get(name)
    if binding is None:
        return "poll"
    if binding.entity_key in get_push_entities():
        return "push"
    return "poll"


def source_for_entity_key(key: str) -> str:
    return "push" if str(key or "").strip() in get_push_entities() else "poll"


def source_for_ehal_id(ehal_id: str) -> str:
    """``push`` / ``poll`` for a qualified or bare EHAL ID (UI)."""
    eid = str(ehal_id or "").strip()
    if not eid or eid == "heartbeat":
        return "poll"
    for binding in get_merker_index().values():
        if binding.ehal_id == eid:
            return source_for_entity_key(binding.entity_key)
    if "." not in eid:
        return source_for_entity_key("plant")
    namespace, _, rest = eid.partition(".")
    slug, _, _ = rest.partition(".")
    if namespace == "ess":
        return source_for_entity_key(f"battery:{slug}")
    return source_for_entity_key(f"consumer:{slug}")


def any_push_entities() -> bool:
    return bool(get_push_entities())


# Re-export for callers that already import pilot_id from push_signals.
__all__ = [
    "MerkerBinding",
    "NEVER_PUSH_KINDS",
    "any_push_entities",
    "build_merker_index",
    "clear_source_caches",
    "entity_key",
    "get_merker_index",
    "get_push_entities",
    "is_pushable_kind",
    "load_push_entities_from_config",
    "merker_bindings_from_docs",
    "parse_push_entities",
    "pilot_id",
    "source_for_ehal_id",
    "source_for_entity_key",
    "source_for_merker",
]
