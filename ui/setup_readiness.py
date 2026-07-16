"""Laufzeitprüfung: Greenfield-Onboarding und Freischaltung von Backtesting."""
from __future__ import annotations

import json
from pathlib import Path

from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
)


def _read_json_document(path: str) -> dict:
    target = Path(path)
    if not target.is_file():
        return {}
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            payload = json.loads(target.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _config_has_legacy_flex_entries(raw: dict) -> bool:
    flex = raw.get("flexible_consumers")
    return isinstance(flex, list) and len(flex) > 0


def _consumer_has_live_loxone_wiring(consumer: dict) -> bool:
    if consumer.get("loxone_inputs") or consumer.get("loxone_outputs"):
        return True
    charging = consumer.get("charging_schedule")
    if isinstance(charging, dict) and isinstance(charging.get("loxone"), dict):
        if charging["loxone"]:
            return True
    thermal = consumer.get("thermal_control")
    if isinstance(thermal, dict) and isinstance(thermal.get("loxone"), dict):
        if thermal["loxone"]:
            return True
    return False


def _house_profile_has_live_loxone_consumers(profiles_doc: dict) -> bool:
    """Post-migration 2.0: flex consumers live in house_profiles with Loxone wiring."""
    for _profile_id, profile in _iter_profiles_from_doc(profiles_doc):
        consumers = profile.get("consumers", [])
        if not isinstance(consumers, list):
            continue
        for consumer in consumers:
            if isinstance(consumer, dict) and _consumer_has_live_loxone_wiring(consumer):
                return True
    return False


def needs_planning_onboarding_from_raw(
    raw: dict,
    *,
    profiles_doc: dict | None = None,
) -> bool:
    """True nach Minimal-Bootstrap (keine Live-Verbraucher in config.json)."""
    if _config_has_legacy_flex_entries(raw):
        return False
    if profiles_doc is not None and _house_profile_has_live_loxone_consumers(profiles_doc):
        return False
    flex = raw.get("flexible_consumers")
    if isinstance(flex, list):
        return len(flex) == 0
    return not flex


def needs_planning_onboarding() -> bool:
    """True nach Minimal-Bootstrap (keine Live-Verbraucher in config.json)."""
    raw = _read_json_document(resolve_config_json_path())
    profiles_doc = _read_json_document(resolve_house_profiles_json_path())
    return needs_planning_onboarding_from_raw(raw, profiles_doc=profiles_doc)


def _iter_profiles_from_doc(doc: dict):
    profiles = doc.get("profiles", [])
    if isinstance(profiles, dict):
        for profile_id, profile in profiles.items():
            if isinstance(profile, dict):
                yield str(profile_id).strip(), profile
        return
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict):
                yield str(profile.get("id", "")).strip(), profile


def _has_house_profile_in_doc(doc: dict) -> bool:
    for profile_id, _profile in _iter_profiles_from_doc(doc):
        if profile_id:
            return True
    return False


def _default_house_profile_id_from_doc(doc: dict) -> str:
    """Erstes Hausprofil — Default für Runtime-Szenario."""
    for profile_id, _profile in _iter_profiles_from_doc(doc):
        if profile_id:
            return profile_id
    return ""


def _tariff_id_maps_from_doc(tariffs_doc: dict) -> tuple[set[str], set[str]]:
    import_map = {
        str(item.get("id", "")).strip()
        for item in tariffs_doc.get("import_tariffs", [])
        if isinstance(item, dict) and item.get("id")
    }
    export_map = {
        str(item.get("id", "")).strip()
        for item in tariffs_doc.get("export_tariffs", [])
        if isinstance(item, dict) and item.get("id")
    }
    return import_map, export_map


def missing_house_config_items_for(
    raw: dict,
    *,
    components_path: str,
    house_profiles_path: str,
) -> list[str]:
    """Fehlende Schritte im Hauskonfigurator (Hausprofil, Batterie)."""
    profiles_doc = _read_json_document(house_profiles_path)
    if not needs_planning_onboarding_from_raw(raw, profiles_doc=profiles_doc):
        return []

    missing: list[str] = []
    if not _has_house_profile_in_doc(profiles_doc):
        missing.append("Hausprofil anlegen (Hauskonfigurator → Hausprofil)")
    components_doc = _read_json_document(components_path)
    if not components_doc.get("batteries"):
        missing.append("Batterie anlegen (Hauskonfigurator → Batterien)")
    return missing


def missing_runtime_scenario_items_for(
    raw: dict,
    *,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
    backtesting_scenarios_path: str | None = None,
) -> list[str]:
    """Fehlende Schritte für Live-Szenario und Echtzeit-Umgebung."""
    profiles_doc = _read_json_document(house_profiles_path)
    if not needs_planning_onboarding_from_raw(raw, profiles_doc=profiles_doc):
        return []

    from house_config.scenario_resolution import (
        get_live_scenario_id,
        find_scenario_settings,
    )

    missing: list[str] = []
    scenarios_path = backtesting_scenarios_path or resolve_backtesting_scenarios_json_path()
    live_id = get_live_scenario_id(raw)
    try:
        live_settings = find_scenario_settings(scenarios_path, live_id)
    except ValueError:
        missing.append(
            f"Live-Szenario '{live_id}' anlegen (Szenarieneditor → Szenarien)"
        )
        return missing

    battery_id = str(live_settings.get("battery_id", "") or "").strip()
    components_doc = _read_json_document(components_path)
    batteries = {
        str(item.get("id", "")).strip()
        for item in components_doc.get("batteries", [])
        if isinstance(item, dict) and item.get("id")
    }
    if not battery_id or battery_id not in batteries:
        missing.append("Batterie für Live-Szenario wählen (Echtzeit-Umgebung)")

    import_id = str(live_settings.get("import_tariff_id", "") or "").strip()
    export_id = str(live_settings.get("export_tariff_id", "") or "").strip()
    tariffs_doc = _read_json_document(tariffs_path)
    import_map, export_map = _tariff_id_maps_from_doc(tariffs_doc)
    if not import_id or import_id not in import_map:
        missing.append("Bezugstarif wählen (Echtzeit-Umgebung)")
    if not export_id or export_id not in export_map:
        missing.append("Einspeisetarif wählen (Echtzeit-Umgebung)")

    profile_id = str(live_settings.get("house_profile_id", "") or "").strip()
    if not profile_id:
        profile_id = _default_house_profile_id_from_doc(profiles_doc)
    if not profile_id:
        missing.append("Hausprofil zuordnen (Echtzeit-Umgebung)")
    return missing


def missing_planning_setup_items_for(
    raw: dict,
    *,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
    backtesting_scenarios_path: str | None = None,
) -> list[str]:
    """Fehlende Schritte bis Szenario-Explorer freigeschaltet werden kann."""
    return missing_house_config_items_for(
        raw,
        components_path=components_path,
        house_profiles_path=house_profiles_path,
    ) + missing_runtime_scenario_items_for(
        raw,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        backtesting_scenarios_path=backtesting_scenarios_path,
    )


def is_planning_ready_for(
    raw: dict,
    *,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
    backtesting_scenarios_path: str | None = None,
) -> bool:
    """Alle Mindestanforderungen für Szenario-Explorer erfüllt (explizite Pfade)."""
    profiles_doc = _read_json_document(house_profiles_path)
    if not needs_planning_onboarding_from_raw(raw, profiles_doc=profiles_doc):
        return True
    return not missing_planning_setup_items_for(
        raw,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        backtesting_scenarios_path=backtesting_scenarios_path,
    )


def missing_house_config_items() -> list[str]:
    """Fehlende Schritte im Hauskonfigurator (Hausprofil, Batterie, PV optional)."""
    return missing_house_config_items_for(
        _read_json_document(resolve_config_json_path()),
        components_path=resolve_components_json_path(),
        house_profiles_path=resolve_house_profiles_json_path(),
    )


def missing_runtime_scenario_items() -> list[str]:
    """Fehlende Schritte in Echtzeit-Umgebung / Live-Szenario."""
    return missing_runtime_scenario_items_for(
        _read_json_document(resolve_config_json_path()),
        components_path=resolve_components_json_path(),
        tariffs_path=resolve_tariffs_json_path(),
        house_profiles_path=resolve_house_profiles_json_path(),
    )


def missing_planning_setup_items() -> list[str]:
    """Fehlende Schritte bis Backtesting freigeschaltet werden kann."""
    return missing_planning_setup_items_for(
        _read_json_document(resolve_config_json_path()),
        components_path=resolve_components_json_path(),
        tariffs_path=resolve_tariffs_json_path(),
        house_profiles_path=resolve_house_profiles_json_path(),
    )


def is_house_config_ready() -> bool:
    """Mindestens ein Hausprofil vorhanden (PV und Haus Wärme optional)."""
    if not needs_planning_onboarding():
        return True
    return not missing_house_config_items()


def is_runtime_scenario_ready() -> bool:
    """Runtime-Szenario vollständig (Batterie, Tarife, Hausprofil)."""
    if not needs_planning_onboarding():
        return True
    return not missing_runtime_scenario_items()


def is_live_configuration_complete() -> bool:
    """Live-Konfiguration gespeichert (Live-Szenario + Entitäts-Referenzen)."""
    return is_runtime_scenario_ready()


def is_planning_ready() -> bool:
    """Alle Mindestanforderungen für Backtesting erfüllt."""
    if not needs_planning_onboarding():
        return True
    return is_house_config_ready() and is_runtime_scenario_ready()


def is_setup_navigation_restricted() -> bool:
    """Nur eingeschränkte Konfigurationsseiten anzeigen."""
    return needs_planning_onboarding() and not is_planning_ready()


def is_betrieb_unlocked() -> bool:
    """Cockpit und Manuelle Geräte — erst nach vollständiger Loxone-Merker-Konfiguration."""
    if not needs_planning_onboarding():
        return True
    return _loxone_markers_complete()


def _loxone_markers_complete() -> bool:
    """Prüfung aller benötigten Loxone-Merker — noch nicht implementiert."""
    return False


def is_scenario_editor_unlocked() -> bool:
    """Szenarieneditor nach vollständigem Hauskonfigurator-Schritt (Profil + Batterie)."""
    if not needs_planning_onboarding():
        return True
    return is_house_config_ready()
