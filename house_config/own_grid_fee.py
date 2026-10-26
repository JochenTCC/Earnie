"""*Eigener Arbeitspreis* of a house profile = user grid area ``user_<profile_id>`` (Edibert P2).

The house-profile form offers an own flat Netznutzung work price next to the catalog areas.
Since data model 5 the profile only references a grid area; the own price lives in
``user_grid_fees.json`` (next to ``grid_fees.json``), written through Edibert.
"""
from __future__ import annotations

from typing import Any

# Form value of the area select for "Eigener Arbeitspreis" (never persisted).
OWN_AREA = "__own__"
# Form-only key next to ``area_id`` carrying the own price (never persisted).
OWN_BASE_KEY = "own_base_cent_kwh"


def own_area_id(profile_id: str) -> str:
    from house_config.edibert_tariffs import user_grid_area_id

    return user_grid_area_id(profile_id)


def own_area_label(profile_label: str) -> str:
    return f"Eigener Arbeitspreis – {profile_label}"


def form_area_value(netznutzung: dict[str, Any], profile_id: str) -> str | None:
    """Select value for a stored profile: its own user area shows as *Eigener Arbeitspreis*."""
    area_id = netznutzung.get("area_id")
    if profile_id and area_id == own_area_id(profile_id):
        return OWN_AREA
    return area_id


def own_base_cent_kwh(catalog: dict[str, Any], profile_id: str) -> float | None:
    """Own price of a profile from the merged grid catalog (``None`` = no own area yet)."""
    area = catalog["areas"].get(own_area_id(profile_id)) if profile_id else None
    if area is None:
        return None
    return float(area["base_cent_kwh"]["unmetered_power"])


def persist_own_grid_fee(
    netznutzung: dict[str, Any],
    *,
    profile_id: str,
    profile_label: str,
    land: str | None,
    grid_fees_path: str | None = None,
) -> dict[str, Any]:
    """Netznutzung to store; for *Eigener Arbeitspreis* the user area is written first.

    Returns ``netznutzung`` with ``area_id`` set to ``user_<profile_id>`` and without the
    form-only price key. Fails loud on a missing price or a read-only (Shadow) config.
    """
    out = {key: value for key, value in netznutzung.items() if key != OWN_BASE_KEY}
    if netznutzung.get("area_id") != OWN_AREA:
        return out
    base = netznutzung.get(OWN_BASE_KEY)
    if base is None:
        raise ValueError("Eigener Arbeitspreis (Netznutzung) fehlt.")
    from runtime_store.shadow.mode import is_shadow_config_readonly

    if is_shadow_config_readonly():
        raise ValueError("Shadow Mode: Konfiguration schreibgeschützt (user_grid_fees.json).")
    from house_config.edibert_tariffs import flat_user_grid_area, save_user_grid_area
    from runtime_store.persist_paths import resolve_grid_fees_json_path, user_grid_fees_path_for

    area_id = own_area_id(profile_id)
    area = flat_user_grid_area(
        area_id, float(base), label=own_area_label(profile_label), land=land
    )
    save_user_grid_area(
        user_grid_fees_path_for(grid_fees_path or resolve_grid_fees_json_path()), area
    )
    out["area_id"] = area_id
    return out
