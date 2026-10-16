"""Post-migration validation with real loaders (ConfigMigration P1)."""
from __future__ import annotations

from typing import Any

from runtime_store.data_model import ensure_compatible
from runtime_store.migration.io_util import EARNIE_TRACK_FILES, GRID_FEES_FILE
from runtime_store.migration.types import Docs


def validate_migrated_docs(docs: Docs) -> None:
    """Raise if migrated pack docs are not loadable under the current model."""
    for name, doc in docs.items():
        if name == GRID_FEES_FILE:
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
