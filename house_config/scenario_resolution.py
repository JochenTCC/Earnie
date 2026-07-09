"""Vollständige Auflösung eines Backtesting-Szenarios in flache Parameter."""
from __future__ import annotations

from house_config.entity_resolution import (
    batteries_by_id,
    pv_systems_by_id,
    resolve_battery_into_settings,
    resolve_pv_into_settings,
)
from house_config.planning_flex_bridge import split_planning_generic_consumers
from house_config.profiles_store import load_house_profiles_document
from house_config.tariffs_store import (
    load_tariffs_document,
    resolve_export_tariff_into_settings,
    resolve_import_tariff_into_settings,
)


def resolve_scenario_settings(
    settings: dict,
    *,
    raw_config: dict,
    tariffs_path: str,
    house_profiles_path: str,
    monthly_rates_holder: dict | None = None,
) -> dict:
    """
    Löst battery_id, pv_system_id, import/export_tariff_id und house_profile_id auf.
    Liefert flaches Dict kompatibel mit simulation/engine.py.
    """
    out = dict(settings)
    batteries = batteries_by_id(raw_config)
    pv_systems = pv_systems_by_id(raw_config)
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
        _fixed, flex_consumers = split_planning_generic_consumers(profile)
        if flex_consumers:
            out["_planning_flex_consumers"] = flex_consumers
    return out


def resolve_runtime_settings_for_backtesting(
    raw_config: dict,
    *,
    tariffs_path: str,
    house_profiles_path: str,
    monthly_rates_holder: dict | None = None,
) -> dict:
    """
    Löst runtime_settings für die Backtesting-Baseline auf (nur Offline-Simulation).
    Live-Pfad (_load_dynamic_params) bleibt unverändert bis Backlog 1.26.0.
    """
    runtime = raw_config.get("runtime_settings", {})
    if not isinstance(runtime, dict):
        raise ValueError("runtime_settings muss ein Objekt sein.")
    settings = dict(runtime)
    if not str(settings.get("house_profile_id", "") or "").strip():
        profiles_doc = load_house_profiles_document(house_profiles_path)
        for profile in profiles_doc.get("profiles", {}).values():
            if not isinstance(profile, dict):
                continue
            profile_id = str(profile.get("id", "")).strip()
            if not profile_id:
                continue
            for consumer in profile.get("consumers", []):
                if isinstance(consumer, dict) and consumer.get("type") == "thermal_annual":
                    settings["house_profile_id"] = profile_id
                    break
            if settings.get("house_profile_id"):
                break
    return resolve_scenario_settings(
        settings,
        raw_config=raw_config,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        monthly_rates_holder=monthly_rates_holder,
    )
