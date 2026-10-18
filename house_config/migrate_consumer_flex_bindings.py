"""Rekey legacy ``flex.{slug}.*`` consumer bindings to typed namespaces."""
from __future__ import annotations

from typing import Any

from ehal.qualified_ids import parse_qualified_id, qualified_consumer_id


def _profiles_items(house: dict) -> list[tuple[Any, dict]]:
    profiles = house.get("profiles")
    if isinstance(profiles, dict):
        return [(key, p) for key, p in profiles.items() if isinstance(p, dict)]
    if isinstance(profiles, list):
        return [(i, p) for i, p in enumerate(profiles) if isinstance(p, dict)]
    return []


def consumer_has_legacy_flex_bindings(consumer: dict | None) -> bool:
    if not isinstance(consumer, dict):
        return False
    bindings = consumer.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return False
    for key in bindings:
        parsed = parse_qualified_id(key)
        if parsed and parsed.is_legacy_flex:
            return True
    return False


def house_has_legacy_flex_bindings(house: dict | None) -> bool:
    if not isinstance(house, dict):
        return False
    for _key, profile in _profiles_items(house):
        for consumer in profile.get("consumers") or []:
            if consumer_has_legacy_flex_bindings(
                consumer if isinstance(consumer, dict) else None
            ):
                return True
    return False


def rekey_consumer_flex_bindings(
    consumer: dict,
) -> tuple[dict[str, str], list[str]]:
    """Return (new_bindings, German conflict messages).

    When conflicts are non-empty, ``new_bindings`` is a copy of the input
    (callers must not apply the rekey).
    """
    bindings = consumer.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return {}, []
    cid = str(consumer.get("id") or "").strip()
    ctype = str(consumer.get("type") or "").strip()
    label = str(consumer.get("label") or cid).strip() or cid or "?"
    conflicts: list[str] = []
    flex_moves: list[tuple[str, str, str]] = []  # flex_key, target, addr

    for key, value in bindings.items():
        key_s = str(key)
        parsed = parse_qualified_id(key_s)
        if not parsed or not parsed.is_legacy_flex:
            continue
        if not cid:
            conflicts.append(
                "Verbraucher ohne id hat noch Legacy-Binding "
                f"'{key_s}' — Kennung setzen oder Binding entfernen."
            )
            continue
        target = qualified_consumer_id(cid, ctype, parsed.kind)
        addr = str(value or "").strip()
        existing = str(bindings.get(target) or "").strip()
        if existing and addr and existing != addr:
            conflicts.append(
                f"Verbraucher '{label}' ({cid}): Konflikt zwischen "
                f"'{key_s}'='{addr}' und '{target}'='{existing}'. "
                "Bitte eines der Bindings bereinigen und Migration erneut starten."
            )
            continue
        flex_moves.append((key_s, target, addr))

    if conflicts:
        return {str(k): str(v or "").strip() for k, v in bindings.items()}, conflicts

    out: dict[str, str] = {}
    flex_keys = {src for src, _t, _a in flex_moves}
    for key, value in bindings.items():
        key_s = str(key)
        if key_s in flex_keys:
            continue
        out[key_s] = str(value or "").strip()
    for _src, target, addr in flex_moves:
        existing = str(out.get(target) or "").strip()
        if target not in out:
            out[target] = addr
        elif not existing and addr:
            out[target] = addr
    return out, []


def migrate_house_consumer_flex_bindings(
    house: dict,
) -> tuple[dict, bool, tuple[str, ...]]:
    """Rekey all consumer ``flex.*`` bindings. Returns (house, changed, conflicts)."""
    out = dict(house)
    profiles = out.get("profiles")
    conflicts: list[str] = []
    changed = False

    if isinstance(profiles, dict):
        new_profiles: dict[Any, Any] = {}
        for key, profile in profiles.items():
            if not isinstance(profile, dict):
                new_profiles[key] = profile
                continue
            prof, prof_changed, msgs = _migrate_profile(profile)
            conflicts.extend(msgs)
            changed = changed or prof_changed
            new_profiles[key] = prof
        out["profiles"] = new_profiles
    elif isinstance(profiles, list):
        new_list: list[Any] = []
        for profile in profiles:
            if not isinstance(profile, dict):
                new_list.append(profile)
                continue
            prof, prof_changed, msgs = _migrate_profile(profile)
            conflicts.extend(msgs)
            changed = changed or prof_changed
            new_list.append(prof)
        out["profiles"] = new_list

    return out, changed, tuple(conflicts)


def _migrate_profile(profile: dict) -> tuple[dict, bool, list[str]]:
    consumers_in = list(profile.get("consumers") or [])
    consumers_out: list[Any] = []
    changed = False
    conflicts: list[str] = []
    for raw in consumers_in:
        if not isinstance(raw, dict):
            consumers_out.append(raw)
            continue
        if not consumer_has_legacy_flex_bindings(raw):
            consumers_out.append(raw)
            continue
        new_bindings, msgs = rekey_consumer_flex_bindings(raw)
        conflicts.extend(msgs)
        if msgs:
            consumers_out.append(raw)
            continue
        old = {
            str(k): str(v or "").strip()
            for k, v in (raw.get("ehal_bindings") or {}).items()
        }
        if new_bindings != old:
            changed = True
            consumers_out.append({**raw, "ehal_bindings": new_bindings})
        else:
            consumers_out.append(raw)
    if not changed and not conflicts:
        return profile, False, []
    return {**profile, "consumers": consumers_out}, changed, conflicts
