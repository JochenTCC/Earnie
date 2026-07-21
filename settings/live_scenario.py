"""Live-scenario resolve, feed-in/wear helpers, and entity-ref mutations."""
from __future__ import annotations

from typing import Any, Callable

from settings.json_io import read_json_dict, write_json_dict

RUNTIME_REF_KEYS = frozenset({
    "battery_id",
    "pv_system_id",
    "pv_system_ids",
    "import_tariff_id",
    "export_tariff_id",
    "house_profile_id",
})
DEPRECATED_RUNTIME_GEO_KEYS = frozenset({
    "latitude",
    "longitude",
    "timezone_name",
})
DEPRECATED_RUNTIME_FLAT_KEYS = frozenset({
    "k_push_cent",
    "feed_in_mode",
    "pv_tilt",
    "pv_azimuth",
    "pv_kwp",
    "battery_max_power_kw",
    "battery_efficiency",
    "battery_capacity_kwh",
    "battery_min_soc",
    "battery_max_soc",
    "threshold_power",
})


def normalize_runtime_settings_key(key: str) -> str:
    return str(key).strip().lower()


def resolve_scenario_settings_dict(
    settings: dict,
    *,
    raw_config: dict,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
) -> dict:
    from house_config.scenario_resolution import resolve_scenario_settings

    holder: dict = {}
    resolved = resolve_scenario_settings(
        settings,
        raw_config=raw_config,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        monthly_rates_holder=holder,
    )
    if holder.get("_monthly_fixed_tariffs") is not None:
        resolved["_monthly_fixed_tariffs"] = holder["_monthly_fixed_tariffs"]
    return resolved


def get_battery_wear_cent_per_kwh(
    *,
    resolved: dict,
    live_scenario_id: str,
    backtesting_scenarios_path: str,
    capacity_kwh: float,
) -> float:
    from optimizer.battery_wear import battery_wear_cent_per_kwh_from_config

    wear_raw = resolved.get("_battery_wear")
    if wear_raw is not None:
        return battery_wear_cent_per_kwh_from_config(wear_raw, float(capacity_kwh))

    from house_config.scenario_resolution import find_scenario_settings

    try:
        live_settings = find_scenario_settings(
            backtesting_scenarios_path,
            live_scenario_id,
        )
    except ValueError:
        return 0.0
    battery_id = str(live_settings.get("battery_id", "") or "").strip()
    if battery_id:
        raise ValueError(
            f"Live-Szenario '{live_scenario_id}': battery_wear fehlt in batteries[] "
            "(Pflicht wenn battery_id gesetzt)."
        )
    return 0.0


def get_feed_in_settings(runtime: dict):
    from data.feed_in_prices import feed_in_settings_from_dict

    monthly = runtime.get("_monthly_fixed_tariffs")
    return feed_in_settings_from_dict(
        runtime,
        monthly_fixed_tariffs=monthly,
    )


def get_backtesting_feed_in_settings(
    runtime: dict,
    *,
    load_scenarios_document: Callable[[], dict],
    load_tariffs_document: Callable[[], dict],
):
    """Einspeise-Settings für Backtesting inkl. monatlicher Fixtarife."""
    from data.feed_in_prices import feed_in_settings_from_dict

    _ = (load_scenarios_document, load_tariffs_document)
    monthly = None
    if runtime.get("_monthly_fixed_tariffs") is not None:
        monthly = runtime["_monthly_fixed_tariffs"]
    return feed_in_settings_from_dict(
        runtime,
        monthly_fixed_tariffs=monthly,
    )


def _find_live_scenario_entry(scenarios: list, live_id: str, scenarios_path: str) -> dict:
    for item in scenarios:
        if isinstance(item, dict) and str(item.get("id", "") or "").strip() == live_id:
            return item
    raise ValueError(
        f"Unbekanntes Live-Szenario '{live_id}' in '{scenarios_path}'."
    )


def _apply_live_ref_updates(
    settings: dict,
    new_settings: dict,
    *,
    live_id: str,
) -> None:
    for raw_key, value in new_settings.items():
        key = normalize_runtime_settings_key(raw_key)
        if key in DEPRECATED_RUNTIME_FLAT_KEYS:
            raise KeyError(
                f"Sicherheitsfehler: '{raw_key}' ist ein deprecated flaches Feld — "
                "bearbeiten Sie batteries[], pv_systems[] oder tariffs.json."
            )
        if key in DEPRECATED_RUNTIME_GEO_KEYS:
            raise KeyError(
                f"Sicherheitsfehler: '{raw_key}' gehört zum Hausprofil — "
                "bearbeiten Sie latitude/longitude/timezone_name in house_profiles.json."
            )
        if key not in RUNTIME_REF_KEYS:
            raise KeyError(
                f"Sicherheitsfehler: '{raw_key}' ist kein zulässiger "
                f"Szenario-Referenzparameter (Live-Szenario '{live_id}')."
            )
        settings[key] = value
    if "pv_system_ids" in new_settings:
        settings.pop("pv_system_id", None)


def update_live_scenario_settings(
    *,
    backtesting_scenarios_path: str,
    live_scenario_id: str,
    new_settings: dict,
) -> None:
    """Persistiert Entitäts-Referenzen im Live-Szenario (backtesting_scenarios.json)."""
    doc = read_json_dict(backtesting_scenarios_path)
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError(
            f"'{backtesting_scenarios_path}' benötigt ein 'scenarios'-Array."
        )
    entry = _find_live_scenario_entry(scenarios, live_scenario_id, backtesting_scenarios_path)
    settings = entry.get("settings")
    if not isinstance(settings, dict):
        raise ValueError(
            f"Live-Szenario '{live_scenario_id}' benötigt ein 'settings'-Objekt."
        )
    _apply_live_ref_updates(settings, new_settings, live_id=live_scenario_id)
    write_json_dict(backtesting_scenarios_path, doc)


def set_live_scenario_id(
    *,
    config_path: str,
    backtesting_scenarios_path: str,
    scenario_id: str,
) -> None:
    """Setzt live_scenario_id in config.json (Szenario muss existieren)."""
    from house_config.scenario_resolution import find_scenario_settings

    normalized = str(scenario_id or "").strip()
    if not normalized:
        raise ValueError("live_scenario_id darf nicht leer sein.")
    find_scenario_settings(backtesting_scenarios_path, normalized)
    raw = read_json_dict(config_path)
    raw["live_scenario_id"] = normalized
    write_json_dict(config_path, raw)


def get_backtesting_scenarios(
    scenarios: list[dict],
    *,
    resolve_settings: Callable[[dict], dict],
) -> dict[str, dict]:
    """Alle aufgelösten Szenarien aus backtesting_scenarios.json."""
    return {
        scenario["id"]: resolve_settings(scenario["settings"])
        for scenario in scenarios
    }


def get_planning_pv_systems(
    *,
    planning_pv_systems: list | None,
    pv_kwp: float,
    pv_tilt: float,
    pv_azimuth: float,
) -> list[dict]:
    """Resolved PV systems from the live scenario (empty when deferred/bootstrap)."""
    if isinstance(planning_pv_systems, list) and planning_pv_systems:
        return [dict(item) for item in planning_pv_systems]
    if float(pv_kwp or 0.0) <= 0.0:
        return []
    return [
        {
            "id": "pv",
            "label": "PV",
            "pv_kwp": float(pv_kwp),
            "pv_tilt": float(pv_tilt or 0.0),
            "pv_azimuth": float(pv_azimuth or 0.0),
        }
    ]


def require_runtime_params_loaded(
    *,
    deferred: bool,
    raw_config: dict,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
    backtesting_scenarios_path: str,
) -> None:
    """Erzwingt vollständig aufgelöste PV-/Batterie-/Tarif-Parameter (Live-Optimierung)."""
    if not deferred:
        return
    from ui.setup_readiness import missing_planning_setup_items_for

    missing = missing_planning_setup_items_for(
        raw_config,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        backtesting_scenarios_path=backtesting_scenarios_path,
    )
    detail = "; ".join(missing) if missing else "unbekannte Lücken"
    raise RuntimeError(
        "Planungs-Konfiguration unvollständig — Optimierung nicht möglich. "
        f"Fehlende Schritte: {detail}"
    )


def runtime_settings_snapshot(get_attr: Callable[..., Any]) -> dict:
    return {
        "PV_KWP": get_attr("PV_KWP", cast=float),
        "PV_TILT": get_attr("PV_TILT", cast=float),
        "PV_AZIMUTH": get_attr("PV_AZIMUTH", cast=float),
        "K_PUSH_CENT": get_attr("K_PUSH_CENT", cast=float),
        "BATTERY_CAPACITY_KWH": get_attr("BATTERY_CAPACITY_KWH", cast=float),
        "BATTERY_MIN_SOC": get_attr("BATTERY_MIN_SOC", cast=float),
        "BATTERY_MAX_SOC": get_attr("BATTERY_MAX_SOC", cast=float),
        "BATTERY_MAX_POWER_KW": get_attr("BATTERY_MAX_POWER_KW", cast=float),
        "THRESHOLD_POWER": get_attr("THRESHOLD_POWER", cast=float),
    }


def battery_params_snapshot(get_attr: Callable[..., Any]) -> dict:
    return {
        "battery_capacity_kwh": get_attr("BATTERY_CAPACITY_KWH", cast=float),
        "min_soc": get_attr("BATTERY_MIN_SOC", cast=float),
        "max_soc": get_attr("BATTERY_MAX_SOC", cast=float),
        "max_power_kw": get_attr("BATTERY_MAX_POWER_KW", cast=float),
        "efficiency": get_attr("BATTERY_EFFICIENCY", cast=float),
    }


def scenario_explorer_conf_snapshot(obj: Any) -> dict:
    return {
        "path_price": obj.PATH_PRICE,
        "path_cons_data": obj.PATH_CONS_DATA,
        "cons_data_retention_months": obj.CONS_DATA_RETENTION_MONTHS,
        "cons_data_write_mode": obj.CONS_DATA_WRITE_MODE,
        "price_source": obj.PRICE_SOURCE,
        "price_provider": obj.PRICE_PROVIDER,
        "price_range": obj.PRICE_RANGE,
        "energy_charts_bzn": obj.ENERGY_CHARTS_BZN,
    }
