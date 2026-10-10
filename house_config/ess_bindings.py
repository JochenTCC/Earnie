"""Merge Pattern B ESS bindings from batteries[] for Live adapters (2.7.c)."""
from __future__ import annotations

from ehal.ess_fields import ess_ehal_slug, parse_ess_pattern_b, plant_flat_ess_keys
from house_config.powerstation import is_house_battery


def _battery_ids(batteries: list[dict]) -> list[str]:
    return [
        str(b.get("id") or "").strip()
        for b in batteries
        if str(b.get("id") or "").strip()
    ]


def _primary_for_flat_aliases(
    selected: list[str],
    by_id: dict[str, dict],
) -> str:
    """House battery first — powerstations must not own plant-flat ESS aliases."""
    for bat_id in selected:
        bat = by_id.get(bat_id)
        if bat is not None and is_house_battery(bat):
            return bat_id
    return selected[0] if selected else ""


def merge_ess_bindings_into_plant(
    plant_bindings: dict | None,
    batteries: list[dict] | None,
    *,
    battery_ids: list[str] | None = None,
) -> dict[str, str]:
    """Return plant-facing bindings with ESS Pattern B + flat aliases for primary.

    Adapters that still expect flat ``sens_ess_*`` / ``set_ess_*`` on plant keep
    working when the primary **house** battery has ``ess.{slug}.*`` bindings.
    Powerstations stay on Pattern-B keys only (no plant-flat takeover).
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

    by_id = {
        str(b.get("id") or "").strip(): b
        for b in bats
        if str(b.get("id") or "").strip()
    }
    selected = [i for i in (battery_ids or []) if i in by_id]
    if not selected:
        selected = _battery_ids(bats)

    primary = _primary_for_flat_aliases(selected, by_id)

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
                # Quellenwahl stays Pattern B only (standby_backup; never plant flat).
                if kind == "set_ess_source_select":
                    continue
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
