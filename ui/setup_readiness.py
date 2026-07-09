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


def missing_planning_setup_items() -> list[str]:
    """Fehlende Schritte bis Backtesting freigeschaltet werden kann."""
    if not needs_planning_onboarding():
        return []

    missing: list[str] = []
    raw = _read_json_document(resolve_config_json_path())
    if not raw.get("pv_systems"):
        missing.append("PV-Anlage (Hauskonfigurator → PV-Anlage)")
    if not raw.get("batteries"):
        missing.append("Batterie (Hauskonfigurator → Batterie)")
    if not _has_thermal_house_profile():
        missing.append("Hausprofil mit thermischem Verbraucher (Hauskonfigurator → Hausprofil)")

    runtime = raw.get("runtime_settings", {})
    if not isinstance(runtime, dict):
        runtime = {}
    import_id = str(runtime.get("import_tariff_id", "") or "").strip()
    export_id = str(runtime.get("export_tariff_id", "") or "").strip()
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
    if not import_id or import_id not in import_map:
        missing.append("Bezugstarif wählen (Hauskonfigurator → Tarife)")
    if not export_id or export_id not in export_map:
        missing.append("Einspeisetarif wählen (Hauskonfigurator → Tarife)")
    return missing


def is_planning_ready() -> bool:
    """Alle Mindestanforderungen für Backtesting erfüllt."""
    if not needs_planning_onboarding():
        return True
    return not missing_planning_setup_items()


def is_setup_navigation_restricted() -> bool:
    """Nur Hauskonfigurator und Konfiguration anzeigen."""
    return needs_planning_onboarding() and not is_planning_ready()


def is_scenario_editor_unlocked() -> bool:
    """Szenarieneditor folgt in einem späteren Schritt — vorerst gesperrt."""
    return not needs_planning_onboarding()
