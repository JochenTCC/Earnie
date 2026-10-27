"""Post-migration validation with real loaders (ConfigMigration P1)."""
from __future__ import annotations

from typing import Any

from runtime_store.data_model import ensure_compatible, ensure_tariff_format
from runtime_store.migration.io_util import EARNIE_TRACK_FILES, TARIFF_TRACK_FILES
from runtime_store.migration.types import Docs


def validate_migrated_docs(docs: Docs) -> None:
    """Raise if migrated pack docs are not loadable under the current model."""
    for name, doc in docs.items():
        if name in TARIFF_TRACK_FILES:
            ensure_tariff_format(doc, label=name)
            continue
        if name in EARNIE_TRACK_FILES:
            ensure_compatible(doc, label=name)

    components = docs.get("components.json")
    if isinstance(components, dict):
        from house_config.inverter import (
            reject_if_needs_conversion_efficiency_migration,
            reject_if_needs_inverter_migration,
        )
        from house_config.migrate_topology import reject_if_needs_topology_migration

        reject_if_needs_inverter_migration(components, path="components.json")
        reject_if_needs_conversion_efficiency_migration(
            components, path="components.json"
        )
        reject_if_needs_topology_migration(components, path="components.json")

    house = docs.get("house_profiles.json")
    config = docs.get("config.json")
    scenarios = docs.get("backtesting_scenarios.json")
    if isinstance(scenarios, dict):
        _reject_unknown_house_profile_refs(
            scenarios, house if isinstance(house, dict) else {}
        )
    if isinstance(house, dict):
        _reject_legacy_grid_fee(house)
        _reject_unresolved_netznutzung(house, docs)
        from house_config.ehal_bindings import ensure_migrated

        ensure_migrated(
            house,
            config if isinstance(config, dict) else None,
            strip_legacy=False,
            migrate_secrets=False,
        )


def _reject_legacy_grid_fee(house: dict[str, Any]) -> None:
    legacy = "netznutzung_arbeitspreis_cent_kwh"
    profiles = house.get("profiles")
    items = profiles.values() if isinstance(profiles, dict) else profiles
    if not isinstance(items, (list, tuple)):
        return
    for profile in items:
        if isinstance(profile, dict) and legacy in profile:
            raise ValueError(
                "house_profiles.json: netznutzung_arbeitspreis_cent_kwh noch vorhanden — "
                "Migration dm4.grid_fee_profile ausführen "
                "(python -m scripts.migrate_config)."
            )


def _grid_area_ids(docs: Docs) -> set[str]:
    ids: set[str] = set()
    for name in ("grid_fees.json", "user_grid_fees.json"):
        areas = (docs.get(name) or {}).get("areas")
        if isinstance(areas, list):
            ids.update(str(a.get("id")) for a in areas if isinstance(a, dict) and a.get("id"))
    return ids


def _reject_unresolved_netznutzung(house: dict[str, Any], docs: Docs) -> None:
    """Data model 5: every profile names a grid area that the pack (catalog or user) has."""
    from house_config.netznutzung import normalize_netznutzung_config

    profiles = house.get("profiles")
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles
    if not isinstance(items, list):
        return
    check_ids = "grid_fees.json" in docs
    known = _grid_area_ids(docs)
    for profile in items:
        if not isinstance(profile, dict):
            continue
        label = f"house_profiles.json: Hausprofil '{profile.get('id', '?')}': netznutzung"
        area_id = normalize_netznutzung_config(profile.get("netznutzung"), label=label)["area_id"]
        if check_ids and area_id not in known:
            raise ValueError(
                f"{label}: Netzbereich '{area_id}' fehlt in grid_fees.json und "
                "user_grid_fees.json."
            )


def _house_profile_ids(house: dict[str, Any]) -> set[str]:
    profiles = house.get("profiles")
    if isinstance(profiles, dict):
        return {str(key) for key in profiles}
    if isinstance(profiles, list):
        return {
            str(profile.get("id") or "").strip()
            for profile in profiles
            if isinstance(profile, dict) and str(profile.get("id") or "").strip()
        }
    return set()


def _reject_unknown_house_profile_refs(
    scenarios_doc: dict[str, Any], house: dict[str, Any]
) -> None:
    """Scenario resolution aborts on unknown profile ids — catch it before writing."""
    entries = scenarios_doc.get("scenarios")
    if not isinstance(entries, list):
        return
    known = _house_profile_ids(house)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            continue
        ref = str(settings.get("house_profile_id") or "").strip()
        if ref and ref not in known:
            raise ValueError(
                f"backtesting_scenarios.json: Szenario '{entry.get('id', '?')}' "
                f"verweist auf unbekannte house_profile_id '{ref}' "
                f"(vorhanden: {', '.join(sorted(known)) or 'keine'}). "
                "Bitte den Verweis korrigieren, dann erneut migrieren."
            )
