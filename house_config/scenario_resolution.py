"""Vollständige Auflösung eines Backtesting-Szenarios in flache Parameter."""
from __future__ import annotations

from house_config.components_store import load_components_document
from house_config.entity_resolution import resolve_components_into_settings
from house_config.geo_timezone import timezone_for_land
from house_config.planning_flex_bridge import collect_planning_flex_consumers
from house_config.profiles_store import load_house_profiles_document
from house_config.tariffs_store import (
    USER_EXPORT_CENT_KEY,
    USER_IMPORT_CENT_KEY,
    is_user_fixed_tariff_id,
    parse_user_export_cent,
    parse_user_import_cent,
    resolve_export_tariff_id,
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
    grid_fees_path: str | None = None,
) -> dict:
    """
    Löst battery_id, pv_system_ids, import/export_tariff_id
    und house_profile_id auf. Liefert flaches Dict kompatibel mit simulation/engine.py.
    """
    out = dict(settings)
    # Tolerate on-disk legacy singular until ConfigMigration persists battery_ids[].
    if "battery_id" in out:
        raw = out.pop("battery_id")
        existing = out.get("battery_ids")
        if not (isinstance(existing, list) and existing):
            bat_id = str(raw or "").strip()
            out["battery_ids"] = [bat_id] if bat_id else []
    if components is None:
        if not components_path:
            raise ValueError("components_path oder components erforderlich.")
        components = load_components_document(components_path)
    out = resolve_components_into_settings(out, components)

    import_tariff_id = _pop_tariff_id(out, "import_tariff_id")
    export_tariff_id = _pop_tariff_id(out, "export_tariff_id")
    if export_tariff_id:
        export_tariff_id = resolve_export_tariff_id(export_tariff_id)
    _reject_legacy_feed_in_keys(out)
    user_cents = _pop_user_fixed_cents(out, import_tariff_id, export_tariff_id)

    profile_id = out.pop("house_profile_id", None)
    profile: dict | None = None
    if profile_id:
        profiles_doc = load_house_profiles_document(house_profiles_path)
        profiles = profiles_doc.get("profiles", {})
        profile_id = str(profile_id).strip()
        if profile_id not in profiles:
            raise ValueError(f"Unbekannte house_profile_id '{profile_id}'.")
        profile = profiles[profile_id]
        out["_house_profile"] = profile
        _apply_profile_geo(out, profile)
        flex_consumers = collect_planning_flex_consumers(profile)
        if flex_consumers:
            out["_planning_flex_consumers"] = flex_consumers
    _ensure_geo_defaults(out)
    _attach_tariffs(
        out,
        tariffs_path=tariffs_path,
        grid_fees_path=grid_fees_path,
        import_tariff_id=import_tariff_id,
        export_tariff_id=export_tariff_id,
        user_cents=user_cents,
        profile=profile,
    )
    return out


def _pop_tariff_id(out: dict, key: str) -> str | None:
    tariff_id = str(out.pop(key, None) or "").strip()
    return tariff_id or None


# Flat feed-in keys of the pre-tariff era; the export tariff prices every slot (Edibert P3b).
_LEGACY_FEED_IN_KEYS = ("k_push_cent", "feed_in_mode", "monthly_fixed_feed_in_rates")


def _reject_legacy_feed_in_keys(out: dict) -> None:
    present = [key for key in _LEGACY_FEED_IN_KEYS if key in out]
    if present:
        raise ValueError(
            f"Szenario-Einstellungen {', '.join(present)} werden nicht mehr unterstützt — "
            "Einspeisetarif über export_tariff_id wählen (z. B. Eigener Festpreis); "
            "Konfiguration migrieren: Streamlit-Seite „Konfigurations-Migration“ oder "
            "python -m scripts.migrate_config --config-dir <config>."
        )


def _pop_user_fixed_cents(
    out: dict, import_tariff_id: str | None, export_tariff_id: str | None
) -> dict[str, float]:
    """Cent values of *Eigener Festpreis*; the keys leave the settings in every case."""
    cents: dict[str, float] = {}
    if is_user_fixed_tariff_id(import_tariff_id):
        cents["import"] = parse_user_import_cent(out)
    if is_user_fixed_tariff_id(export_tariff_id):
        cents["export"] = parse_user_export_cent(out)
    out.pop(USER_IMPORT_CENT_KEY, None)
    out.pop(USER_EXPORT_CENT_KEY, None)
    return cents


def _user_fixed_vat(profile: dict | None) -> float:
    """VAT of *Eigener Festpreis* import: the profile country's rate (VAT on the net grid fee).

    Without a house profile there is no grid fee, so the gross price needs no rate.
    """
    from house_config.edibert_tariffs import STANDARD_VAT_PERCENT

    if profile is None:
        return 0.0
    land = str(profile.get("land", "AT") or "AT").strip().upper()
    if land not in STANDARD_VAT_PERCENT:
        raise ValueError(f"Keine Standard-USt für Land {land!r} (AT, DE oder CH).")
    return float(STANDARD_VAT_PERCENT[land])


def _attach_tariffs(
    out: dict,
    *,
    tariffs_path: str,
    grid_fees_path: str | None,
    import_tariff_id: str | None,
    export_tariff_id: str | None,
    user_cents: dict[str, float],
    profile: dict | None,
) -> None:
    """Pricing reference (``_edibert_pricing``) plus the tariff parameters for display.

    Prices come only from Edibert through the reference (Edibert P3b). A scenario without a
    tariff keeps no price source: pricing it fails with ``import_tariff_id fehlt`` /
    ``export_tariff_id fehlt`` (decision D2, no live-tariff or constant fallback).
    """
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, pricing_reference, tariff
    from house_config.edibert_tariffs import EXPORT, IMPORT, market_zone, tariff_info
    from runtime_store.persist_paths import resolve_grid_fees_json_path

    user_fixed: dict[str, dict[str, float]] = {}
    if "import" in user_cents:
        user_fixed[IMPORT] = {"cent": user_cents["import"], "vat_percent": _user_fixed_vat(profile)}
    if "export" in user_cents:
        user_fixed[EXPORT] = {"cent": user_cents["export"], "vat_percent": 0.0}
    ref = pricing_reference(
        tariffs_path=tariffs_path,
        grid_fees_path=grid_fees_path or resolve_grid_fees_json_path(),
        import_tariff_id=import_tariff_id,
        export_tariff_id=export_tariff_id,
        timezone_name=out["timezone_name"],
        profile=profile,
        user_fixed=user_fixed,
    )
    out[EDIBERT_PRICING_KEY] = ref
    if import_tariff_id:
        info = tariff_info(tariff(ref, IMPORT))
        out["_import_tariff_spec"] = info
        if "land" in info:
            out["market_zone"] = market_zone(info["land"])
    if export_tariff_id:
        info = tariff_info(tariff(ref, EXPORT))
        out["_export_tariff_spec"] = info
        # Constant of a fixed export tariff for history fallbacks (``K_PUSH_CENT``);
        # slot prices always come from the tariff.
        out["k_push_cent"] = float(info.get("k_push_cent", 0.0) or 0.0)


def _ensure_geo_defaults(out: dict) -> None:
    """Fallback für Bootstrap ohne Hausprofil (bis Planung vollständig)."""
    if "latitude" not in out:
        out["latitude"] = 48.2
    if "longitude" not in out:
        out["longitude"] = 16.37
    if not str(out.get("timezone_name", "") or "").strip():
        out["timezone_name"] = timezone_for_land("AT")


def _apply_profile_geo(out: dict, profile: dict) -> None:
    """Geo/Zeitzone immer aus Hausprofil (Szenario-lat/lon/timezone werden ignoriert)."""
    out["latitude"] = float(profile["latitude"])
    out["longitude"] = float(profile["longitude"])
    out["timezone_name"] = str(profile.get("timezone_name", "") or "").strip()
    if not out["timezone_name"]:
        out["timezone_name"] = timezone_for_land(profile.get("land", "AT"))


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
    )
