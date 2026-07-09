"""Laufzeitprüfung: Greenfield-Onboarding und Freischaltung von Backtesting."""
from __future__ import annotations

import json
from pathlib import Path

from runtime_store.persist_paths import (
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


def needs_planning_onboarding() -> bool:
    """True nach Minimal-Bootstrap (keine Live-Verbraucher in config.json)."""
    raw = _read_json_document(resolve_config_json_path())
    return not raw.get("flexible_consumers")


def _has_thermal_house_profile() -> bool:
    doc = _read_json_document(resolve_house_profiles_json_path())
    for profile in doc.get("profiles", []):
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers", []):
            if isinstance(consumer, dict) and consumer.get("type") == "thermal_annual":
                return True
    return False


def _default_house_profile_id() -> str:
    """Erstes Hausprofil mit thermischem Verbraucher — Default für Runtime-Szenario."""
    doc = _read_json_document(resolve_house_profiles_json_path())
    for profile in doc.get("profiles", []):
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id", "")).strip()
        if not profile_id:
            continue
        for consumer in profile.get("consumers", []):
            if isinstance(consumer, dict) and consumer.get("type") == "thermal_annual":
                return profile_id
    return ""


def _runtime_settings() -> dict:
    raw = _read_json_document(resolve_config_json_path())
    runtime = raw.get("runtime_settings", {})
    return runtime if isinstance(runtime, dict) else {}


def _tariff_id_maps() -> tuple[set[str], set[str]]:
    tariffs = _read_json_document(resolve_tariffs_json_path())
    import_map = {
        str(item.get("id", "")).strip()
        for item in tariffs.get("import_tariffs", [])
        if isinstance(item, dict) and item.get("id")
    }
    export_map = {
        str(item.get("id", "")).strip()
        for item in tariffs.get("export_tariffs", [])
        if isinstance(item, dict) and item.get("id")
    }
    return import_map, export_map


def missing_house_config_items() -> list[str]:
    """Fehlende Schritte im Hauskonfigurator (Verbraucher + PV)."""
    if not needs_planning_onboarding():
        return []

    missing: list[str] = []
    raw = _read_json_document(resolve_config_json_path())
    if not raw.get("pv_systems"):
        missing.append("PV-Anlage (Hauskonfigurator → PV-Anlage)")
    if not _has_thermal_house_profile():
        missing.append("Hausprofil mit thermischem Verbraucher (Hauskonfigurator → Hausprofil)")
    return missing


def missing_runtime_scenario_items() -> list[str]:
    """Fehlende Schritte im Runtime-Szenario (Szenarieneditor)."""
    if not needs_planning_onboarding():
        return []

    missing: list[str] = []
    raw = _read_json_document(resolve_config_json_path())
    if not raw.get("batteries"):
        missing.append("Batterie anlegen (Szenarieneditor → Batterien)")

    runtime = _runtime_settings()
    battery_id = str(runtime.get("battery_id", "") or "").strip()
    batteries = {
        str(item.get("id", "")).strip()
        for item in raw.get("batteries", [])
        if isinstance(item, dict) and item.get("id")
    }
    if not battery_id or battery_id not in batteries:
        missing.append("Batterie für Runtime wählen (Szenarieneditor → Runtime)")

    import_id = str(runtime.get("import_tariff_id", "") or "").strip()
    export_id = str(runtime.get("export_tariff_id", "") or "").strip()
    import_map, export_map = _tariff_id_maps()
    if not import_id or import_id not in import_map:
        missing.append("Bezugstarif wählen (Szenarieneditor → Runtime)")
    if not export_id or export_id not in export_map:
        missing.append("Einspeisetarif wählen (Szenarieneditor → Runtime)")

    profile_id = str(runtime.get("house_profile_id", "") or "").strip()
    if not profile_id:
        profile_id = _default_house_profile_id()
    if not profile_id:
        missing.append("Hausprofil zuordnen (Szenarieneditor → Runtime)")
    return missing


def missing_planning_setup_items() -> list[str]:
    """Fehlende Schritte bis Backtesting freigeschaltet werden kann."""
    return missing_house_config_items() + missing_runtime_scenario_items()


def is_house_config_ready() -> bool:
    """Hausprofil + PV vollständig."""
    if not needs_planning_onboarding():
        return True
    return not missing_house_config_items()


def is_runtime_scenario_ready() -> bool:
    """Runtime-Szenario vollständig (Batterie, Tarife, Hausprofil)."""
    if not needs_planning_onboarding():
        return True
    return not missing_runtime_scenario_items()


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
    """Szenarieneditor nach vollständigem Hauskonfigurator-Schritt."""
    if not needs_planning_onboarding():
        return True
    return is_house_config_ready()
