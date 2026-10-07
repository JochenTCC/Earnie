"""Freeze component entity ids after the first intentional Bezeichnung change.

New batteries / PV systems start unlocked with ``id_provisional_label`` = seed
label. When the saved label first differs, the id becomes ``slug_id(label)``
and ``id_locked`` turns true. Legacy entities without the flag are locked.
"""
from __future__ import annotations

from ehal.ess_fields import ess_ehal_slug, parse_ess_pattern_b
from house_config.id_slug import slug_id

ID_LOCKED_KEY = "id_locked"
ID_PROVISIONAL_LABEL_KEY = "id_provisional_label"


def is_id_locked(entity: dict | None) -> bool:
    """True when id must not auto-change (missing flag ⇒ legacy locked)."""
    if not isinstance(entity, dict):
        return True
    if ID_LOCKED_KEY not in entity:
        return True
    return bool(entity.get(ID_LOCKED_KEY))


def provisional_label(entity: dict | None) -> str:
    if not isinstance(entity, dict):
        return ""
    return str(entity.get(ID_PROVISIONAL_LABEL_KEY) or "").strip()


def rewrite_ess_bindings_slug(
    bindings: dict | None,
    *,
    old_id: str,
    new_id: str,
) -> dict[str, str]:
    """Rewrite Pattern B keys ``ess.{old}.*`` → ``ess.{new}.*``."""
    if not isinstance(bindings, dict):
        return {}
    old_slug = ess_ehal_slug(old_id)
    new_slug = ess_ehal_slug(new_id)
    out: dict[str, str] = {}
    for key, value in bindings.items():
        addr = str(value or "").strip()
        if not addr:
            continue
        field = str(key)
        parsed = parse_ess_pattern_b(field)
        if parsed and parsed[0] == old_slug:
            field = f"ess.{new_slug}.{parsed[1]}"
        if field not in out:
            out[field] = addr
    return out


def resolve_id_on_save(
    *,
    label: str,
    stable_id: str,
    existing: dict | None,
    taken: set[str],
    provisional_from_ui: str = "",
    force_from_label: bool = False,
) -> tuple[str, bool, str]:
    """Return ``(entity_id, id_locked, provisional_label)`` for upsert.

    ``force_from_label``: one-shot UI action — slug from current label and lock.
    """
    label_s = str(label or "").strip()
    stable = str(stable_id or "").strip()
    taken_ids = set(taken)

    if force_from_label:
        if stable:
            taken_ids.discard(stable)
        new_id = slug_id(label_s or stable or "eintrag", existing=taken_ids)
        return new_id, True, ""

    if not stable:
        # Brand-new entity: unlocked until Bezeichnung leaves the seed label.
        seed = str(provisional_from_ui or label_s).strip() or "eintrag"
        new_id = slug_id(label_s or seed, existing=taken_ids)
        return new_id, False, seed

    locked = is_id_locked(existing)
    if locked:
        return stable, True, ""

    seed = provisional_label(existing) or str(provisional_from_ui or "").strip()
    if seed and label_s and label_s != seed:
        taken_ids.discard(stable)
        new_id = slug_id(label_s, existing=taken_ids)
        return new_id, True, ""

    return stable, False, seed or label_s
