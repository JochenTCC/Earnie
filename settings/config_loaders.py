"""Static and runtime attribute loaders extracted from config.Config."""
from __future__ import annotations

import json
import os
from typing import Any

from runtime_store.persist_paths import resolve_dotenv_path
from settings import legacy_config_gates
from settings import system_settings
from settings.json_io import read_json_dict


def get_strict(source: dict, keys_path: list, config_path: str) -> Any:
    current = source
    for key in keys_path:
        if not isinstance(current, dict) or key not in current:
            raise KeyError(
                f"Kritischer Konfigurationsfehler: Der Parameter '{'.'.join(keys_path)}' "
                f"fehlt in {config_path}!"
            )
        current = current[key]
    return current


def validate_threshold_power(value) -> float:
    rel = float(value)
    if rel <= 0.0 or rel > 1.0:
        raise ValueError(
            "Kritischer Konfigurationsfehler: runtime_settings.threshold_power "
            "muss ein relativer Anteil zwischen 0 (exklusiv) und 1 (inklusiv) sein."
        )
    return rel


def load_local_settings_document(local_settings_path: str) -> dict:
    path = local_settings_path
    if not os.path.isfile(path):
        return {}
    try:
        return read_json_dict(path)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Kritischer Fehler: '{path}' enthält ungültiges JSON: {e}"
        ) from e


def load_env_vars(*, require_loxone_credentials: bool) -> dict[str, Any]:
    attrs = {
        "LOXONE_IP": os.getenv("LOXONE_IP"),
        "LOXONE_USER": os.getenv("LOXONE_USER"),
        "LOXONE_PASS": os.getenv("LOXONE_PASS"),
    }
    if require_loxone_credentials and not all(attrs.values()):
        missing = [k for k in attrs if not os.getenv(k)]
        dotenv_path = resolve_dotenv_path()
        raise ValueError(
            f"Kritischer Fehler: Fehlende sensible Daten in '{dotenv_path}': "
            f"{', '.join(missing)}"
        )
    return attrs


def load_system_and_ui_params(
    raw_config: dict,
    *,
    local_settings_path: str,
    event_triggers: list[dict],
    config_path: str,
) -> dict[str, Any]:
    local_settings = load_local_settings_document(local_settings_path)
    return {
        "GLOBAL_TIMEOUT": get_strict(raw_config, ["system", "global_timeout"], config_path),
        "LOOP_TIMEOUT": get_strict(raw_config, ["system", "loop_timeout"], config_path),
        "LOXONE_SILENT_MODE": system_settings.load_loxone_silent_mode(
            raw_config, local_settings, local_settings_path
        ),
        "EVENT_TRIGGER_ENABLED": system_settings.load_event_trigger_enabled(raw_config),
        "EVENT_POLL_INTERVAL_SEC": system_settings.load_event_poll_interval_sec(raw_config),
        "EVENT_TRIGGERS": event_triggers,
        "UI_FRAGMENT_REFRESH_CHARTS_SEC": system_settings.load_ui_fragment_refresh_sec(
            raw_config, "fragment_refresh_charts_sec", 60
        ),
        "UI_FRAGMENT_REFRESH_STATUS_SEC": system_settings.load_ui_fragment_refresh_sec(
            raw_config, "fragment_refresh_status_sec", 10
        ),
        "UI_MAIN_SYNC_POLL_SEC": system_settings.load_ui_fragment_refresh_sec(
            raw_config, "main_sync_poll_sec", 15
        ),
        "UI_CHART_DEBUG_CAPTURE_ENABLED": system_settings.load_ui_chart_debug_capture_enabled(
            raw_config, local_settings, local_settings_path
        ),
        "UI_CHART_DEBUG_CAPTURE_DIR": system_settings.load_ui_chart_debug_capture_dir(
            raw_config
        ),
        "UI_STREAMLIT_PORT": system_settings.load_ui_streamlit_port(raw_config),
        "UI_PRICE_FORECAST_PAGE_ENABLED": system_settings.load_ui_bool(
            raw_config, "price_forecast_page_enabled", False
        ),
    }


def load_loxone_block_params(raw_config: dict, config_path: str) -> dict[str, Any]:
    keys = (
        ("LOXONE_SOC_NAME", ["loxone_blocks", "soc_name"]),
        ("LOXONE_PV_COUNTER_NAME", ["loxone_blocks", "pv_counter_name"]),
        ("LOXONE_LOG_FILENAME", ["loxone_blocks", "log_filename"]),
        ("PV_TUNING_LOG_FILE", ["loxone_blocks", "pv_tuning_log_file"]),
        ("LOXONE_PV_POWER_NAME", ["loxone_blocks", "pv_power_name"]),
        ("LOXONE_BATTERY_POWER_NAME", ["loxone_blocks", "battery_power_name"]),
        ("LOXONE_GRID_POWER_NAME", ["loxone_blocks", "grid_power_name"]),
        ("LOXONE_TARGET_SOC_NAME", ["loxone_blocks", "target_soc_name"]),
        ("LOXONE_TARGET_CHARGE_POWER_NAME", ["loxone_blocks", "target_charge_power_name"]),
        ("LOXONE_TARGET_DISCHARGE_POWER_NAME", ["loxone_blocks", "target_discharge_power_name"]),
        ("LOXONE_CONTROL_CMD_NAME", ["loxone_blocks", "control_cmd_name"]),
    )
    return {
        attr: get_strict(raw_config, path, config_path) for attr, path in keys
    }


def load_sim_path_params(raw_config: dict) -> dict[str, Any]:
    sim_paths = raw_config.get("scenario_explorer_conf", {})
    return {
        "PATH_PRICE": sim_paths.get("path_price", ""),
        "PATH_CONS_DATA": sim_paths.get("path_cons_data", "runtime/cons_data_hourly.csv"),
        "CONS_DATA_RETENTION_MONTHS": sim_paths.get("cons_data_retention_months", 24),
        "CONS_DATA_WRITE_MODE": sim_paths.get("cons_data_write_mode", "hourly"),
        "PRICE_SOURCE": sim_paths.get("price_source", "csv"),
        "PRICE_PROVIDER": sim_paths.get("price_provider", "awattar"),
        "PRICE_RANGE": sim_paths.get("price_range", "last_12_months"),
        "ENERGY_CHARTS_BZN": sim_paths.get("energy_charts_bzn", "DE-LU"),
    }


def lookup_runtime_value(resolved: dict, key: str, config_path: str):
    if key in resolved:
        return resolved[key]
    raise KeyError(
        f"Kritischer Konfigurationsfehler: aufgelöstes runtime_settings.{key} "
        f"fehlt — prüfen Sie Entitäts-IDs in {config_path}."
    )


def resolve_live_scenario_settings_dict(
    raw_config: dict,
    *,
    backtesting_scenarios_path: str,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
) -> dict:
    from house_config.scenario_resolution import resolve_live_scenario_settings

    holder: dict = {}
    resolved = resolve_live_scenario_settings(
        raw_config,
        backtesting_scenarios_path=backtesting_scenarios_path,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        monthly_rates_holder=holder,
    )
    if holder.get("_monthly_fixed_tariffs") is not None:
        resolved["_monthly_fixed_tariffs"] = holder["_monthly_fixed_tariffs"]
    return resolved


def should_defer_runtime_params(
    raw_config: dict,
    *,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
    backtesting_scenarios_path: str,
) -> bool:
    from runtime_store.env_vars import is_explicit_offline
    from runtime_store.offline_demo_seed import live_scenario_refs_incomplete
    from ui.setup_readiness import (
        is_planning_ready_for,
        needs_planning_onboarding_from_raw,
    )

    # Cloud / offline: empty live refs must not abort config load (seed may not
    # have catalogs yet; UI can still open for house/scenario setup).
    if is_explicit_offline() and live_scenario_refs_incomplete(
        scenarios_path=backtesting_scenarios_path,
    ):
        return True

    if not needs_planning_onboarding_from_raw(raw_config):
        return False
    return not is_planning_ready_for(
        raw_config,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        backtesting_scenarios_path=backtesting_scenarios_path,
    )


def load_planning_horizon_mode(raw_config: dict) -> str:
    planning_raw = raw_config.get("planning_horizon", {})
    if not isinstance(planning_raw, dict):
        raise ValueError(
            "Kritischer Konfigurationsfehler: Block 'planning_horizon' ist ungültig."
        )
    mode_raw = planning_raw.get("mode")
    if mode_raw is None:
        raise ValueError(
            "Kritischer Konfigurationsfehler: planning_horizon.mode fehlt in config.json."
        )
    return str(mode_raw)


def load_geo_timezone_params(
    resolved: dict,
    raw_config: dict,
    config_path: str,
) -> dict[str, Any]:
    return {
        "LATITUDE": float(lookup_runtime_value(resolved, "latitude", config_path)),
        "LONGITUDE": float(lookup_runtime_value(resolved, "longitude", config_path)),
        "PLANNING_TIMEZONE": str(
            lookup_runtime_value(resolved, "timezone_name", config_path)
        ),
        "PLANNING_HORIZON_MODE": load_planning_horizon_mode(raw_config),
    }


def load_deferred_runtime_params(
    resolved: dict,
    raw_config: dict,
    config_path: str,
) -> dict[str, Any]:
    attrs = {
        "FEED_IN_MODE": "fixed",
        "_planning_pv_systems": [],
    }
    attrs.update(load_geo_timezone_params(resolved, raw_config, config_path))
    return attrs


def _planning_pv_systems_from_resolved(resolved: dict) -> list[dict]:
    planning_pv = resolved.get("_planning_pv_systems")
    if isinstance(planning_pv, list):
        return [dict(item) for item in planning_pv]
    return []


def load_full_runtime_params(
    resolved: dict,
    raw_config: dict,
    config_path: str,
) -> dict[str, Any]:
    feed_in_mode_raw = resolved.get("feed_in_mode")
    if feed_in_mode_raw is None:
        feed_in_mode = "fixed"
    else:
        from data.feed_in_prices import validate_feed_in_mode

        feed_in_mode = validate_feed_in_mode(feed_in_mode_raw)

    attrs: dict[str, Any] = {
        "FEED_IN_MODE": feed_in_mode,
        "K_PUSH_CENT": float(lookup_runtime_value(resolved, "k_push_cent", config_path)),
        "PV_TILT": float(resolved.get("pv_tilt", 0.0) or 0.0),
        "PV_AZIMUTH": float(resolved.get("pv_azimuth", 0.0) or 0.0),
        "PV_KWP": float(resolved.get("pv_kwp", 0.0) or 0.0),
        "_planning_pv_systems": _planning_pv_systems_from_resolved(resolved),
        "BATTERY_MAX_POWER_KW": float(
            lookup_runtime_value(resolved, "battery_max_power_kw", config_path)
        ),
        "BATTERY_EFFICIENCY": float(
            lookup_runtime_value(resolved, "battery_efficiency", config_path)
        ),
        "BATTERY_CAPACITY_KWH": float(
            lookup_runtime_value(resolved, "battery_capacity_kwh", config_path)
        ),
        "BATTERY_MIN_SOC": float(
            lookup_runtime_value(resolved, "battery_min_soc", config_path)
        ),
        "BATTERY_MAX_SOC": float(
            lookup_runtime_value(resolved, "battery_max_soc", config_path)
        ),
        "THRESHOLD_POWER": validate_threshold_power(
            lookup_runtime_value(resolved, "threshold_power", config_path)
        ),
    }
    attrs.update(load_geo_timezone_params(resolved, raw_config, config_path))
    return attrs


def load_dynamic_params(
    raw_config: dict,
    *,
    config_path: str,
    backtesting_scenarios_path: str,
    components_path: str,
    tariffs_path: str,
    house_profiles_path: str,
) -> dict[str, Any]:
    legacy_config_gates.reject_legacy_config_blocks(raw_config)
    legacy_config_gates.reject_legacy_runtime_settings_block(raw_config)
    resolved = resolve_live_scenario_settings_dict(
        raw_config,
        backtesting_scenarios_path=backtesting_scenarios_path,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
    )
    from house_config.awattar_api import resolve_awattar_api_url

    attrs: dict[str, Any] = {
        "_resolved_runtime_settings": resolved,
        "AWATTAR_URL": resolve_awattar_api_url(resolved),
    }
    deferred = should_defer_runtime_params(
        raw_config,
        components_path=components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
        backtesting_scenarios_path=backtesting_scenarios_path,
    )
    attrs["_runtime_params_deferred"] = deferred
    if deferred:
        attrs.update(load_deferred_runtime_params(resolved, raw_config, config_path))
    else:
        attrs.update(load_full_runtime_params(resolved, raw_config, config_path))
    return attrs


def apply_attrs(target: Any, attrs: dict[str, Any]) -> None:
    for key, value in attrs.items():
        setattr(target, key, value)
