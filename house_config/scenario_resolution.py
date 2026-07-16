"""Vollständige Auflösung eines Backtesting-Szenarios in flache Parameter."""
from __future__ import annotations

from house_config.components_store import load_components_document
from house_config.entity_resolution import (
    batteries_by_id,
    pv_systems_by_id,
    resolve_battery_into_settings,
    resolve_pv_into_settings,
)
from house_config.geo_timezone import lookup_timezone_name
from house_config.planning_flex_bridge import collect_planning_flex_consumers
from house_config.profiles_store import load_house_profiles_document
from house_config.tariffs_store import (
    load_tariffs_document,
    resolve_export_tariff_into_settings,
    resolve_import_tariff_into_settings,
)
from settings.scenarios import load_backtesting_scenarios_document

DEFAULT_LIVE_SCENARIO_ID = "live"


def get_live_scenario_id(raw_config: dict) -> str:
    """Live-Szenario-ID aus config.json (Standard: ``live``)."""
    raw = raw_config.get("live_scenario_id", DEFAULT_LIVE_SCENARIO_ID)
    scenario_id = str(raw or DEFAULT_LIVE_SCENARIO_ID).strip()
    return scenario_id or DEFAULT_LIVE_SCENARIO_ID


def find_scenario_entry(
    backtesting_scenarios_path: str,
    scenario_id: str,
) -> dict:
    """Liefert den Roh-Eintrag aus backtesting_scenarios.json."""
    doc = load_backtesting_scenarios_document(backtesting_scenarios_path)
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: '{backtesting_scenarios_path}' "
            "benötigt ein 'scenarios'-Array."
        )
    target = str(scenario_id or "").strip()
    for index, entry in enumerate(scenarios):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id", "") or "").strip() == target:
            return entry
    raise ValueError(
        f"Unbekanntes Szenario '{target}' in '{backtesting_scenarios_path}'."
    )


def find_scenario_settings(
    backtesting_scenarios_path: str,
    scenario_id: str,
) -> dict:
    """Liefert settings-Dict eines Szenarios."""
    entry = find_scenario_entry(backtesting_scenarios_path, scenario_id)
    settings = entry.get("settings")
    if not isinstance(settings, dict):
        raise ValueError(
            f"Szenario '{scenario_id}' benötigt ein 'settings'-Objekt in "
            f"'{backtesting_scenarios_path}'."
        )
    return dict(settings)


def resolve_scenario_settings(
    settings: dict,
    *,
    raw_config: dict,
    components_path: str | None = None,
    components: dict | None = None,
    tariffs_path: str,
    house_profiles_path: str,
    monthly_rates_holder: dict | None = None,
) -> dict:
    """
    Löst battery_id, pv_system_id, import/export_tariff_id und house_profile_id auf.
    Liefert flaches Dict kompatibel mit simulation/engine.py.
    """
    out = dict(settings)
    if components is None:
        if not components_path:
            raise ValueError("components_path oder components erforderlich.")
        components = load_components_document(components_path)
    batteries = batteries_by_id(components)
    pv_systems = pv_systems_by_id(components)
    out = resolve_battery_into_settings(out, batteries)
    out = resolve_pv_into_settings(out, pv_systems)

    tariffs_doc = load_tariffs_document(tariffs_path)
    holder = monthly_rates_holder if monthly_rates_holder is not None else {}
    out = resolve_import_tariff_into_settings(out, tariffs_doc)
    out = resolve_export_tariff_into_settings(
        out, tariffs_doc, monthly_rates_holder=holder
    )

    profile_id = out.pop("house_profile_id", None)
    if profile_id:
        profiles_doc = load_house_profiles_document(house_profiles_path)
        profiles = profiles_doc.get("profiles", {})
        profile_id = str(profile_id).strip()
        if profile_id not in profiles:
            raise ValueError(f"Unbekannte house_profile_id '{profile_id}'.")
        profile = profiles[profile_id]
        out["_house_profile"] = profile
        _apply_profile_geo(out, profile, settings)
        flex_consumers = collect_planning_flex_consumers(profile)
        if flex_consumers:
            out["_planning_flex_consumers"] = flex_consumers
    _ensure_geo_defaults(out)
    return out


def _ensure_geo_defaults(out: dict) -> None:
    """Fallback für Bootstrap ohne Hausprofil (bis Planung vollständig)."""
    if "latitude" not in out:
        out["latitude"] = 48.2
    if "longitude" not in out:
        out["longitude"] = 16.37
    if not str(out.get("timezone_name", "") or "").strip():
        out["timezone_name"] = lookup_timezone_name(
            float(out["latitude"]),
            float(out["longitude"]),
        )


def _apply_profile_geo(out: dict, profile: dict, source_settings: dict) -> None:
    """Geo/Zeitzone aus Hausprofil; explizite Szenario-Overrides bleiben erhalten."""
    if "latitude" not in source_settings:
        out["latitude"] = float(profile["latitude"])
    if "longitude" not in source_settings:
        out["longitude"] = float(profile["longitude"])
    if "timezone_name" not in source_settings or not str(
        source_settings.get("timezone_name", "") or ""
    ).strip():
        out["timezone_name"] = str(profile.get("timezone_name", "") or "").strip()
        if not out["timezone_name"]:
            out["timezone_name"] = lookup_timezone_name(
                float(out.get("latitude", profile["latitude"])),
                float(out.get("longitude", profile["longitude"])),
            )


def _prepare_live_scenario_settings(
    settings: dict,
    *,
    house_profiles_path: str,
) -> dict:
    """Geo aus Hausprofil; Default-Hausprofil wenn leer."""
    prepared = dict(settings)
    if str(prepared.get("house_profile_id", "") or "").strip():
        for geo_key in ("latitude", "longitude", "timezone_name"):
            prepared.pop(geo_key, None)
    if not str(prepared.get("house_profile_id", "") or "").strip():
        profiles_doc = load_house_profiles_document(house_profiles_path)
        for profile_id, profile in profiles_doc.get("profiles", {}).items():
            if not isinstance(profile, dict):
                continue
            profile_id = str(profile_id or profile.get("id", "")).strip()
            if profile_id:
                prepared["house_profile_id"] = profile_id
                break
    return prepared


def resolve_live_scenario_settings(
    raw_config: dict,
    *,
    backtesting_scenarios_path: str,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
    monthly_rates_holder: dict | None = None,
) -> dict:
    """
    Löst das Live-Szenario (live_scenario_id) für Echtzeit und Szenario-Explorer auf.
    Erfordert Entitäts-IDs im Szenario (keine flachen Legacy-Felder in config.json).
    """
    scenario_id = get_live_scenario_id(raw_config)
    settings = find_scenario_settings(backtesting_scenarios_path, scenario_id)
    prepared = _prepare_live_scenario_settings(
        settings,
        house_profiles_path=house_profiles_path,
    )
    return resolve_scenario_settings(
        prepared,
        raw_config=raw_config,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        monthly_rates_holder=monthly_rates_holder,
    )


def resolve_legacy_runtime_settings(
    raw_config: dict,
    *,
    components_path: str | None = None,
    components: dict | None = None,
    tariffs_path: str,
    house_profiles_path: str,
    monthly_rates_holder: dict | None = None,
) -> dict:
    """
    Legacy-Auflösung aus config.json runtime_settings (nur Migration 1.26.0 P5).
    """
    runtime = raw_config.get("runtime_settings", {})
    if not isinstance(runtime, dict):
        raise ValueError("runtime_settings muss ein Objekt sein.")
    settings = dict(runtime)
    prepared = _prepare_live_scenario_settings(
        settings,
        house_profiles_path=house_profiles_path,
    )
    return resolve_scenario_settings(
        prepared,
        raw_config=raw_config,
        components_path=components_path,
        components=components,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        monthly_rates_holder=monthly_rates_holder,
    )
