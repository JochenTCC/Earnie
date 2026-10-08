"""Push vs poll source for Loxone VO telemetry (push-only for pushable fields).

Pushable ``sens_*`` / ``get_*`` always read from the inbox. Meter ``*_energy``
via ``/all`` stays on poll. Legacy ``ehal.loxone_push.entities`` is ignored
(tolerated in config for one release).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from ehal.push_signals import pilot_id
from ehal.qualified_ids import field_kind

logger = logging.getLogger(__name__)

# Meter ``/all`` energy stays on poll forever (not a VO push).
NEVER_PUSH_KINDS: frozenset[str] = frozenset()
_ENERGY_KIND_SUFFIX = "_energy"


@dataclass(frozen=True)
class MerkerBinding:
    """One pushable EHAL ID, optionally still keyed by a legacy Merker name."""

    merker: str
    ehal_id: str
    entity_key: str
    kind: str


def entity_key(entity_kind: str, entity_id: str) -> str:
    """Stable entity key (``plant``, ``battery:…``, ``consumer:…``)."""
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
    """Deprecated: parse legacy ``ehal.loxone_push.entities`` (ignored at runtime)."""
    if not isinstance(raw, list):
        return frozenset()
    keys: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if text:
            keys.add(text)
    return frozenset(keys)


def load_push_entities_from_config(raw_config: dict | None = None) -> frozenset[str]:
    """Deprecated: always empty — push is the default for pushable fields."""
    del raw_config
    return frozenset()


def is_pushable_kind(kind: str) -> bool:
    """False for fields that never go through the VO push path."""
    k = field_kind(kind)
    if k in NEVER_PUSH_KINDS:
        return False
    if k.endswith(_ENERGY_KIND_SUFFIX):
        return False
    return k.startswith(("sens_", "get_"))


def merker_bindings_from_docs(house: dict, components: dict) -> list[MerkerBinding]:
    """All pushable field bindings from saved house/components docs.

    Merker name may be empty (push-only read via qualified EHAL ID).
    """
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
        if not is_pushable_kind(field):
            continue
        ehal_id = pilot_id(kind, eid, field, ctype)
        if ehal_id is None:
            continue
        out.append(
            MerkerBinding(
                merker=str(name or "").strip(),
                ehal_id=ehal_id,
                entity_key=entity_key(kind, eid),
                kind=field_kind(field),
            )
        )
    return out


def build_merker_index(
    house: dict, components: dict
) -> dict[str, MerkerBinding]:
    """``{merker_name: MerkerBinding}`` for non-empty Merker names (last wins)."""
    index: dict[str, MerkerBinding] = {}
    for binding in merker_bindings_from_docs(house, components):
        if binding.merker:
            index[binding.merker] = binding
    return index


def build_ehal_index(
    house: dict, components: dict
) -> dict[str, MerkerBinding]:
    """``{ehal_id: MerkerBinding}`` for every pushable binding (last wins)."""
    index: dict[str, MerkerBinding] = {}
    for binding in merker_bindings_from_docs(house, components):
        index[binding.ehal_id] = binding
    return index


_index_cache: dict[str, MerkerBinding] | None = None
_ehal_index_cache: dict[str, MerkerBinding] | None = None
_index_mtime_key: tuple[float, float] | None = None


def clear_source_caches() -> None:
    """Reset lazy caches (tests / after config reload)."""
    global _index_cache, _ehal_index_cache, _index_mtime_key
    _index_cache = None
    _ehal_index_cache = None
    _index_mtime_key = None


def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return -1.0


def _house_components_mtime_key() -> tuple[float, float]:
    from runtime_store.persist_paths import (
        resolve_components_json_path,
        resolve_house_profiles_json_path,
    )

    return (
        _file_mtime(resolve_house_profiles_json_path()),
        _file_mtime(resolve_components_json_path()),
    )


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


def _ensure_indexes() -> None:
    global _index_cache, _ehal_index_cache, _index_mtime_key
    mtime_key = _house_components_mtime_key()
    if (
        _index_cache is not None
        and _ehal_index_cache is not None
        and _index_mtime_key == mtime_key
    ):
        return
    try:
        house, components = _load_house_components()
        _index_cache = build_merker_index(house, components)
        _ehal_index_cache = build_ehal_index(house, components)
        _index_mtime_key = mtime_key
    except Exception:  # noqa: BLE001 — read path must keep working
        logger.exception("loxone push: failed to build binding indexes")
        _index_cache = {}
        _ehal_index_cache = {}
        _index_mtime_key = mtime_key


def get_merker_index() -> dict[str, MerkerBinding]:
    _ensure_indexes()
    assert _index_cache is not None
    return _index_cache


def get_ehal_index() -> dict[str, MerkerBinding]:
    _ensure_indexes()
    assert _ehal_index_cache is not None
    return _ehal_index_cache


def resolve_push_binding(io_or_ehal: str) -> MerkerBinding | None:
    """Look up a pushable binding by Merker name or qualified/bare EHAL ID."""
    name = str(io_or_ehal or "").strip()
    if not name:
        return None
    binding = get_merker_index().get(name)
    if binding is not None:
        return binding
    return get_ehal_index().get(name)


def get_push_entities() -> frozenset[str]:
    """Deprecated: always empty (push is unconditional for pushable fields)."""
    return frozenset()


def source_for_merker(merker: str) -> str:
    """Return ``push`` for indexed pushable Merkers, else ``poll``."""
    binding = resolve_push_binding(merker)
    if binding is None:
        return "poll"
    return "push" if is_pushable_kind(binding.kind) else "poll"


def source_for_entity_key(key: str) -> str:
    """Entity keys are always push once the migration is complete."""
    return "push" if str(key or "").strip() else "poll"


def source_for_ehal_id(ehal_id: str) -> str:
    """``push`` for heartbeat and pushable IDs; ``poll`` for energy / unknown empty."""
    eid = str(ehal_id or "").strip()
    if not eid:
        return "poll"
    if eid == "heartbeat":
        return "push"
    kind = field_kind(eid)
    if kind.endswith(_ENERGY_KIND_SUFFIX):
        return "poll"
    if is_pushable_kind(kind):
        return "push"
    binding = get_ehal_index().get(eid)
    if binding is not None and is_pushable_kind(binding.kind):
        return "push"
    return "poll"


def any_push_entities() -> bool:
    """True when any pushable binding exists (legacy name kept for callers)."""
    return bool(get_ehal_index())


# Re-export for callers that already import pilot_id from push_signals.
__all__ = [
    "MerkerBinding",
    "NEVER_PUSH_KINDS",
    "any_push_entities",
    "build_ehal_index",
    "build_merker_index",
    "clear_source_caches",
    "entity_key",
    "get_ehal_index",
    "get_merker_index",
    "get_push_entities",
    "is_pushable_kind",
    "load_push_entities_from_config",
    "merker_bindings_from_docs",
    "parse_push_entities",
    "pilot_id",
    "resolve_push_binding",
    "source_for_ehal_id",
    "source_for_entity_key",
    "source_for_merker",
]
