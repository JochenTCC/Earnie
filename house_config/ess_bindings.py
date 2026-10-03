"""Merge Pattern B ESS bindings from batteries[] for Live adapters (2.7.c)."""
from __future__ import annotations

from ehal.ess_fields import ess_ehal_slug, parse_ess_pattern_b, plant_flat_ess_keys


def merge_ess_bindings_into_plant(
    plant_bindings: dict | None,
    batteries: list[dict] | None,
    *,
    battery_ids: list[str] | None = None,
) -> dict[str, str]:
    """Return plant-facing bindings with ESS Pattern B + flat aliases for primary.

    Adapters that still expect flat ``sens_ess_*`` / ``set_ess_*`` on plant keep
    working when the primary selected battery has ``ess.{slug}.*`` bindings.
    """
    out: dict[str, str] = {}
    if isinstance(plant_bindings, dict):
        for key, value in plant_bindings.items():
            addr = str(value or "").strip()
            if addr:
                out[str(key)] = addr

    bats = [b for b in (batteries or []) if isinstance(b, dict)]
    if not bats:
        return out

    selected = list(battery_ids or [])
    if not selected:
        selected = [str(b.get("id") or "").strip() for b in bats if str(b.get("id") or "").strip()]

    by_id = {str(b.get("id") or "").strip(): b for b in bats if str(b.get("id") or "").strip()}
    primary = selected[0] if selected else ""

    for bat_id in selected:
        bat = by_id.get(bat_id)
        if not bat:
            continue
        bindings = bat.get("ehal_bindings")
        if not isinstance(bindings, dict):
            continue
        slug = ess_ehal_slug(bat_id)
        for key, value in bindings.items():
            addr = str(value or "").strip()
            if not addr:
                continue
            field = str(key)
            out[field] = addr
            parsed = parse_ess_pattern_b(field)
            if parsed and parsed[0] == slug and bat_id == primary:
                kind = parsed[1]
                if kind not in out:
                    out[kind] = addr
    return out


def primary_flat_ess_from_batteries(
    batteries: list[dict] | None,
    *,
    battery_ids: list[str] | None = None,
) -> dict[str, str]:
    """Flat ESS keys for the primary battery only (for migrate diagnostics)."""
    merged = merge_ess_bindings_into_plant({}, batteries, battery_ids=battery_ids)
    return plant_flat_ess_keys(merged)
