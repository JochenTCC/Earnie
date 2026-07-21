# config.py
import os
import json

from runtime_store.dotenv_io import loxone_credentials_configured
from runtime_store.dotenv_loader import load_app_dotenv

# Sensible Daten aus .env laden (Prod: config/.env, Dev: Fallback ./.env)
load_app_dotenv()

from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
    resolve_local_settings_json_path,
    resolve_tariffs_json_path,
)
from settings import appliances as appliance_settings
from settings import config_loaders
from settings import flexible_consumers as fc_settings
from settings import live_scenario
from settings import scenarios as scenario_settings
from settings import system_settings
from settings.json_io import read_json_dict

CONFIG_JSON_PATH = resolve_config_json_path()
BACKTESTING_SCENARIOS_JSON_PATH = resolve_backtesting_scenarios_json_path()
LOCAL_SETTINGS_JSON_PATH = resolve_local_settings_json_path()
TARIFFS_JSON_PATH = resolve_tariffs_json_path()
HOUSE_PROFILES_JSON_PATH = resolve_house_profiles_json_path()
COMPONENTS_JSON_PATH = resolve_components_json_path()


def _default_require_loxone_credentials() -> bool:
    from runtime_store.env_vars import is_effective_offline

    if is_effective_offline():
        return False
    return loxone_credentials_configured()


class Config:
    # --- Delegation an settings/* (API-Stabilität für Tests und Caller) ---
    _read_json_dict = staticmethod(read_json_dict)
    _normalize_consumer = staticmethod(fc_settings.normalize_consumer)
    _consumer_has_daily_target = staticmethod(fc_settings.consumer_has_daily_target)
    _charging_efficiency = staticmethod(fc_settings.charging_efficiency)
    target_kwh_from_rest_soc = staticmethod(fc_settings.target_kwh_from_rest_soc)
    target_kwh_from_day_schedule = staticmethod(fc_settings.target_kwh_from_day_schedule)
    _normalize_appliance = staticmethod(appliance_settings.normalize_appliance)
    _optional_positive = staticmethod(appliance_settings.optional_positive)
    _normalize_appliance_recommendation = staticmethod(
        appliance_settings.normalize_appliance_recommendation
    )
    _normalize_scenario = staticmethod(scenario_settings.normalize_scenario)
    _load_loxone_silent_mode = staticmethod(system_settings.load_loxone_silent_mode)
    _load_event_trigger_enabled = staticmethod(system_settings.load_event_trigger_enabled)
    _load_ui_fragment_refresh_sec = staticmethod(system_settings.load_ui_fragment_refresh_sec)
    _load_ui_bool = staticmethod(system_settings.load_ui_bool)
    _load_ui_streamlit_port = staticmethod(system_settings.load_ui_streamlit_port)
    _load_ui_chart_debug_capture_dir = staticmethod(
        system_settings.load_ui_chart_debug_capture_dir
    )
    _load_event_poll_interval_sec = staticmethod(system_settings.load_event_poll_interval_sec)
    _normalize_event_trigger = staticmethod(system_settings.normalize_event_trigger)
    _validate_threshold_power = staticmethod(config_loaders.validate_threshold_power)
    _normalize_runtime_settings_key = staticmethod(
        live_scenario.normalize_runtime_settings_key
    )
    _RUNTIME_REF_KEYS = live_scenario.RUNTIME_REF_KEYS
    _DEPRECATED_RUNTIME_GEO_KEYS = live_scenario.DEPRECATED_RUNTIME_GEO_KEYS
    _DEPRECATED_RUNTIME_FLAT_KEYS = live_scenario.DEPRECATED_RUNTIME_FLAT_KEYS

    def __init__(
        self,
        config_path: str = CONFIG_JSON_PATH,
        backtesting_scenarios_path: str = BACKTESTING_SCENARIOS_JSON_PATH,
        local_settings_path: str = LOCAL_SETTINGS_JSON_PATH,
        tariffs_path: str = TARIFFS_JSON_PATH,
        house_profiles_path: str = HOUSE_PROFILES_JSON_PATH,
        components_path: str = COMPONENTS_JSON_PATH,
        require_loxone_credentials: bool | None = None,
    ):
        self.config_path = config_path
        self.backtesting_scenarios_path = backtesting_scenarios_path
        self.local_settings_path = local_settings_path
        self.tariffs_path = tariffs_path
        self.house_profiles_path = house_profiles_path
        self.components_path = components_path
        if require_loxone_credentials is None:
            require_loxone_credentials = _default_require_loxone_credentials()
        self.require_loxone_credentials = require_loxone_credentials
        self._raw_config = None
        self._components_doc = None
        self._runtime_params_deferred = False
        self._load_all()

    def _load_all(self) -> None:
        self._raw_config = self._load_json()
        self._load_components()
        self._load_env_vars()
        self._load_static_params()
        self._load_dynamic_params()

    def _load_components(self) -> None:
        from house_config.components_store import load_components_document

        self._components_doc = load_components_document(self.components_path)

    def _load_json(self) -> dict:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(
                f"Kritischer Fehler: Die Konfigurationsdatei '{self.config_path}' wurde nicht gefunden!"
            )

        try:
            return read_json_dict(self.config_path)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Kritischer Fehler: '{self.config_path}' enthält ungültiges JSON: {e}"
            ) from e
        except ValueError as e:
            raise ValueError(
                f"Kritischer Fehler: '{self.config_path}' konnte nicht gelesen werden: {e}"
            ) from e

    def _load_event_triggers(self) -> list[dict]:
        return system_settings.load_event_triggers(self._raw_config)

    def _load_env_vars(self) -> None:
        config_loaders.apply_attrs(
            self,
            config_loaders.load_env_vars(
                require_loxone_credentials=self.require_loxone_credentials
            ),
        )

    def _load_static_params(self) -> None:
        config_loaders.apply_attrs(
            self,
            config_loaders.load_system_and_ui_params(
                self._raw_config,
                local_settings_path=self.local_settings_path,
                event_triggers=self._load_event_triggers(),
                config_path=self.config_path,
            ),
        )
        config_loaders.apply_attrs(
            self,
            config_loaders.load_loxone_block_params(self._raw_config, self.config_path),
        )
        config_loaders.apply_attrs(
            self,
            config_loaders.load_sim_path_params(self._raw_config),
        )

    def get_resolved_runtime_settings(self) -> dict:
        """Aufgelöstes Runtime-Szenario (Entitäts-IDs → flache Parameter)."""
        return dict(self._resolved_runtime_settings)

    def is_runtime_params_deferred(self) -> bool:
        """True während Greenfield-Onboarding, bevor Planungs-Konfiguration vollständig ist."""
        return self._runtime_params_deferred

    def require_runtime_params_loaded(self) -> None:
        """Erzwingt vollständig aufgelöste PV-/Batterie-/Tarif-Parameter (Live-Optimierung)."""
        live_scenario.require_runtime_params_loaded(
            deferred=self._runtime_params_deferred,
            raw_config=self._raw_config,
            components_path=self.components_path,
            tariffs_path=self.tariffs_path,
            house_profiles_path=self.house_profiles_path,
            backtesting_scenarios_path=self.backtesting_scenarios_path,
        )

    def _load_dynamic_params(self) -> None:
        config_loaders.apply_attrs(
            self,
            config_loaders.load_dynamic_params(
                self._raw_config,
                config_path=self.config_path,
                backtesting_scenarios_path=self.backtesting_scenarios_path,
                components_path=self.components_path,
                tariffs_path=self.tariffs_path,
                house_profiles_path=self.house_profiles_path,
            ),
        )

    def get_planning_timezone(self) -> str:
        return str(self.PLANNING_TIMEZONE)

    def is_sunrise_planning_horizon(self) -> bool:
        if self.PLANNING_HORIZON_MODE != "sunrise_window":
            raise ValueError(
                "Unbekannter planning_horizon.mode "
                f"'{self.PLANNING_HORIZON_MODE}' — erwartet 'sunrise_window'."
            )
        return True

    def get(self, name: str, default=None, cast=None):
        value = getattr(self, name, default)
        if value is None:
            value = default
        return cast(value) if cast and value is not None else value

    def get_planning_pv_systems(self) -> list[dict]:
        """Resolved PV systems from the live scenario (empty when deferred/bootstrap)."""
        return live_scenario.get_planning_pv_systems(
            planning_pv_systems=getattr(self, "_planning_pv_systems", None),
            pv_kwp=float(getattr(self, "PV_KWP", 0.0) or 0.0),
            pv_tilt=float(getattr(self, "PV_TILT", 0.0) or 0.0),
            pv_azimuth=float(getattr(self, "PV_AZIMUTH", 0.0) or 0.0),
        )

    def get_runtime_settings(self) -> dict:
        return live_scenario.runtime_settings_snapshot(self.get)

    def get_battery_params(self) -> dict:
        return live_scenario.battery_params_snapshot(self.get)

    def get_flexible_consumers(self, optimizer_only: bool = False) -> list:
        """Lädt alle konfigurierten flexiblen Verbraucher."""
        return fc_settings.load_flexible_consumers(
            self._raw_config,
            self.get_resolved_runtime_settings(),
            optimizer_only=optimizer_only,
        )

    def get_appliances(self) -> list[dict]:
        """Manuelle Geräte für den Empfehlungsmodus (aus Hausprofil appliance_recommendation)."""
        profile = self.get_resolved_runtime_settings().get("_house_profile")
        if isinstance(profile, dict):
            return appliance_settings.recommendation_appliances_from_profile(profile)
        return []

    def update_appliance_defaults(
        self,
        appliance_id: str,
        *,
        power_kw: float,
        runtime_h: float,
    ) -> None:
        """Persistiert Nennleistung und Laufzeit-Vorbelegung für ein manuelles Gerät."""
        appliance_settings.update_appliance_defaults_from_resolved(
            self.get_resolved_runtime_settings(),
            self.house_profiles_path,
            appliance_id,
            power_kw=power_kw,
            runtime_h=runtime_h,
        )

    def get_appliance_recommendation_settings(self) -> dict:
        """Schwellen für Sterne-Vergabe bei manuellen Geräten."""
        return appliance_settings.normalize_appliance_recommendation(
            self._raw_config.get("appliance_recommendation")
        )

    def update_appliance_recommendation_settings(self, new_settings: dict) -> None:
        self._raw_config = appliance_settings.update_appliance_recommendation_in_file(
            self.config_path,
            self.get_appliance_recommendation_settings(),
            new_settings,
        )

    def get_battery_wear_cent_per_kwh(self, capacity_kwh: float) -> float:
        """Verschleiß ct/kWh Durchsatz für MILP; aus batteries[] wenn battery_id gesetzt."""
        return live_scenario.get_battery_wear_cent_per_kwh(
            resolved=self.get_resolved_runtime_settings(),
            live_scenario_id=self.get_live_scenario_id(),
            backtesting_scenarios_path=self.backtesting_scenarios_path,
            capacity_kwh=capacity_kwh,
        )

    def get_push_price_cent(self) -> float:
        return self.get('K_PUSH_CENT', cast=float)

    def get_feed_in_settings(self, runtime_override: dict | None = None):
        runtime = (
            runtime_override
            if runtime_override is not None
            else self.get_resolved_runtime_settings()
        )
        return live_scenario.get_feed_in_settings(runtime)

    def get_backtesting_feed_in_settings(self, runtime_override: dict | None = None):
        """Einspeise-Settings für Backtesting inkl. monatlicher Fixtarife."""
        runtime = (
            runtime_override
            if runtime_override is not None
            else self.get_resolved_runtime_settings()
        )
        return live_scenario.get_backtesting_feed_in_settings(
            runtime,
            load_scenarios_document=self._load_backtesting_scenarios_document,
            load_tariffs_document=self._load_tariffs_document,
        )

    def get_threshold_power(self) -> float:
        """Relativer Leistungsschwellenwert (Anteil von battery_max_power_kw)."""
        return self.get('THRESHOLD_POWER', cast=float)

    def get_global_timeout(self, default: int = 5) -> int:
        return self.get('GLOBAL_TIMEOUT', default=default, cast=int)

    def is_loxone_silent_mode(self) -> bool:
        return bool(self.get('LOXONE_SILENT_MODE', default=True))

    def is_event_trigger_enabled(self) -> bool:
        return bool(self.get('EVENT_TRIGGER_ENABLED', default=True))

    def get_event_poll_interval_sec(self) -> int:
        return int(self.get('EVENT_POLL_INTERVAL_SEC', default=60))

    def get_ui_fragment_charts_sec(self) -> int:
        return int(self.get("UI_FRAGMENT_REFRESH_CHARTS_SEC", default=60))

    def get_ui_fragment_status_sec(self) -> int:
        return int(self.get("UI_FRAGMENT_REFRESH_STATUS_SEC", default=10))

    def get_ui_main_sync_poll_sec(self) -> int:
        return int(self.get("UI_MAIN_SYNC_POLL_SEC", default=15))

    def get_ui_chart_debug_capture_enabled(self) -> bool:
        from runtime_store.env_vars import is_truthy

        if is_truthy("UI_CHART_DEBUG_CAPTURE_ENABLED"):
            return True
        return bool(self.get("UI_CHART_DEBUG_CAPTURE_ENABLED", default=False))

    def get_ui_chart_debug_capture_dir(self) -> str:
        return str(self.get("UI_CHART_DEBUG_CAPTURE_DIR", default="chart_debug"))

    def get_ui_streamlit_port(self) -> int:
        return int(self.get("UI_STREAMLIT_PORT", default=8501))

    def get_ui_price_forecast_page_enabled(self) -> bool:
        return bool(self.get("UI_PRICE_FORECAST_PAGE_ENABLED", default=False))

    def get_event_triggers(self) -> list[dict]:
        return list(self.EVENT_TRIGGERS)

    def get_scenario_explorer_conf(self) -> dict:
        """Gibt den Block scenario_explorer_conf aus der JSON-Struktur zurück."""
        return live_scenario.scenario_explorer_conf_snapshot(self)

    def get_scenario_settings(self) -> dict:
        """Lädt Szenario-Parameter als {id: settings}-Dict (Abwärtskompatibilität)."""
        return {scenario["id"]: scenario["settings"] for scenario in self.get_scenarios()}

    def _load_backtesting_scenarios_document(self) -> dict:
        return scenario_settings.load_backtesting_scenarios_document(
            self.backtesting_scenarios_path
        )

    def _load_tariffs_document(self) -> dict:
        return read_json_dict(self.tariffs_path)

    def get_backtesting_cbc_gap_rel(self) -> float:
        return scenario_settings.get_backtesting_cbc_gap_rel(self.backtesting_scenarios_path)

    def get_backtesting_cbc_strict_time_limit_sec(self) -> float:
        return scenario_settings.get_backtesting_cbc_strict_time_limit_sec(
            self.backtesting_scenarios_path
        )

    def _load_backtesting_scenarios_entries(self) -> list:
        return scenario_settings.load_backtesting_scenarios_entries(
            self.backtesting_scenarios_path,
            self._raw_config,
        )

    def get_scenarios(self) -> list[dict]:
        """Lädt alle Backtesting-Szenarien aus backtesting_scenarios.json."""
        raw = self._load_backtesting_scenarios_entries()
        if not raw:
            return []
        return [
            scenario_settings.normalize_scenario(entry, index)
            for index, entry in enumerate(raw)
        ]

    def get_scenario_labels(self) -> dict[str, str]:
        """Anzeigenamen für Scenario-Exploration-Szenarien."""
        return {scenario["id"]: scenario["label"] for scenario in self.get_scenarios()}

    def get_live_scenario_id(self) -> str:
        from house_config.scenario_resolution import get_live_scenario_id

        return get_live_scenario_id(self._raw_config)

    def get_batteries(self) -> list[dict]:
        from house_config.entity_resolution import batteries_by_id

        return list(batteries_by_id(self._components_doc).values())

    def get_pv_systems(self) -> list[dict]:
        from house_config.entity_resolution import pv_systems_by_id

        return list(pv_systems_by_id(self._components_doc).values())

    def get_components_catalog(self) -> dict:
        """Normalisiertes components.json (batteries[], pv_systems[])."""
        return dict(self._components_doc)

    def resolve_scenario_settings_dict(self, settings: dict) -> dict:
        return self._resolve_scenario_settings_dict(settings)

    def _resolve_scenario_settings_dict(self, settings: dict) -> dict:
        return live_scenario.resolve_scenario_settings_dict(
            settings,
            raw_config=self._raw_config,
            components_path=self.components_path,
            tariffs_path=self.tariffs_path,
            house_profiles_path=self.house_profiles_path,
        )

    def get_backtesting_scenarios(self) -> dict[str, dict]:
        """Alle aufgelösten Szenarien aus backtesting_scenarios.json."""
        return live_scenario.get_backtesting_scenarios(
            self.get_scenarios(),
            resolve_settings=self._resolve_scenario_settings_dict,
        )

    def get_value(self, name: str, default=None, cast=None):
        return self.get(name, default=default, cast=cast)

    def reload(self) -> None:
        self._load_all()

    def update_live_scenario_settings(self, new_settings: dict) -> None:
        """Aktualisiert Entitäts-Referenzen im Live-Szenario (backtesting_scenarios.json)."""
        live_scenario.update_live_scenario_settings(
            backtesting_scenarios_path=self.backtesting_scenarios_path,
            live_scenario_id=self.get_live_scenario_id(),
            new_settings=new_settings,
        )
        self._load_dynamic_params()

    def set_live_scenario_id(self, scenario_id: str) -> None:
        """Setzt live_scenario_id in config.json (Szenario muss existieren)."""
        live_scenario.set_live_scenario_id(
            config_path=self.config_path,
            backtesting_scenarios_path=self.backtesting_scenarios_path,
            scenario_id=scenario_id,
        )
        self._load_all()

    def update_runtime_settings(self, new_settings: dict) -> None:
        """Alias für update_live_scenario_settings (API-Stabilität)."""
        self.update_live_scenario_settings(new_settings)


def get_resolved_runtime_settings() -> dict:
    return CONFIG.get_resolved_runtime_settings()


def is_runtime_params_deferred() -> bool:
    return CONFIG.is_runtime_params_deferred()


def require_runtime_params_loaded() -> None:
    CONFIG.require_runtime_params_loaded()


CONFIG = Config(require_loxone_credentials=_default_require_loxone_credentials())


def reinit_config(require_loxone_credentials: bool | None = None) -> None:
    """Lädt die Konfiguration neu (z. B. nach Bootstrap mit neu angelegter config.json)."""
    global CONFIG, CONFIG_JSON_PATH, BACKTESTING_SCENARIOS_JSON_PATH, LOCAL_SETTINGS_JSON_PATH
    global TARIFFS_JSON_PATH, HOUSE_PROFILES_JSON_PATH, COMPONENTS_JSON_PATH
    CONFIG_JSON_PATH = resolve_config_json_path()
    BACKTESTING_SCENARIOS_JSON_PATH = resolve_backtesting_scenarios_json_path()
    LOCAL_SETTINGS_JSON_PATH = resolve_local_settings_json_path()
    TARIFFS_JSON_PATH = resolve_tariffs_json_path()
    HOUSE_PROFILES_JSON_PATH = resolve_house_profiles_json_path()
    COMPONENTS_JSON_PATH = resolve_components_json_path()
    if require_loxone_credentials is None:
        require_loxone_credentials = _default_require_loxone_credentials()
    CONFIG = Config(
        config_path=CONFIG_JSON_PATH,
        backtesting_scenarios_path=BACKTESTING_SCENARIOS_JSON_PATH,
        local_settings_path=LOCAL_SETTINGS_JSON_PATH,
        tariffs_path=TARIFFS_JSON_PATH,
        house_profiles_path=HOUSE_PROFILES_JSON_PATH,
        components_path=COMPONENTS_JSON_PATH,
        require_loxone_credentials=require_loxone_credentials,
    )


def get(name: str, default=None, cast=None):
    return CONFIG.get(name, default=default, cast=cast)


def get_runtime_settings() -> dict:
    return CONFIG.get_runtime_settings()


def get_battery_params() -> dict:
    return CONFIG.get_battery_params()


def get_flexible_consumers(optimizer_only: bool = False) -> list:
    return CONFIG.get_flexible_consumers(optimizer_only=optimizer_only)


def get_appliances() -> list[dict]:
    return CONFIG.get_appliances()


def get_appliance_recommendation_settings() -> dict:
    return CONFIG.get_appliance_recommendation_settings()


def update_appliance_recommendation_settings(new_settings: dict) -> None:
    return CONFIG.update_appliance_recommendation_settings(new_settings)


def get_battery_wear_cent_per_kwh(capacity_kwh: float) -> float:
    return CONFIG.get_battery_wear_cent_per_kwh(capacity_kwh)


def get_push_price_cent() -> float:
    return CONFIG.get_push_price_cent()


def get_feed_in_settings(runtime_override: dict | None = None):
    return CONFIG.get_feed_in_settings(runtime_override=runtime_override)


def get_backtesting_feed_in_settings(runtime_override: dict | None = None):
    return CONFIG.get_backtesting_feed_in_settings(runtime_override=runtime_override)


def get_threshold_power() -> float:
    return CONFIG.get_threshold_power()


def get_planning_timezone() -> str:
    return CONFIG.get_planning_timezone()


def is_sunrise_planning_horizon() -> bool:
    return CONFIG.is_sunrise_planning_horizon()


def get_global_timeout(default: int = 5) -> int:
    return CONFIG.get_global_timeout(default=default)


def is_loxone_silent_mode() -> bool:
    return CONFIG.is_loxone_silent_mode()


def is_event_trigger_enabled() -> bool:
    return CONFIG.is_event_trigger_enabled()


def get_event_poll_interval_sec() -> int:
    return CONFIG.get_event_poll_interval_sec()


def get_ui_fragment_charts_sec() -> int:
    return CONFIG.get_ui_fragment_charts_sec()


def get_ui_fragment_status_sec() -> int:
    return CONFIG.get_ui_fragment_status_sec()


def get_ui_main_sync_poll_sec() -> int:
    return CONFIG.get_ui_main_sync_poll_sec()


def get_ui_chart_debug_capture_enabled() -> bool:
    return CONFIG.get_ui_chart_debug_capture_enabled()


def get_ui_chart_debug_capture_dir() -> str:
    return CONFIG.get_ui_chart_debug_capture_dir()


def get_ui_streamlit_port() -> int:
    return CONFIG.get_ui_streamlit_port()


def get_ui_price_forecast_page_enabled() -> bool:
    return CONFIG.get_ui_price_forecast_page_enabled()


def get_event_triggers() -> list[dict]:
    return CONFIG.get_event_triggers()


def get_scenario_explorer_conf() -> dict:
    return CONFIG.get_scenario_explorer_conf()


def get_scenario_settings() -> dict:
    return CONFIG.get_scenario_settings()


def get_scenarios() -> list[dict]:
    return CONFIG.get_scenarios()


def get_scenario_labels() -> dict[str, str]:
    return CONFIG.get_scenario_labels()


def get_live_scenario_id() -> str:
    return CONFIG.get_live_scenario_id()


def get_backtesting_scenarios() -> dict[str, dict]:
    return CONFIG.get_backtesting_scenarios()


def get_batteries() -> list[dict]:
    return CONFIG.get_batteries()


def get_pv_systems() -> list[dict]:
    return CONFIG.get_pv_systems()


def get_planning_pv_systems() -> list[dict]:
    return CONFIG.get_planning_pv_systems()


def get_backtesting_cbc_gap_rel() -> float:
    return CONFIG.get_backtesting_cbc_gap_rel()


def get_backtesting_cbc_strict_time_limit_sec() -> float:
    return CONFIG.get_backtesting_cbc_strict_time_limit_sec()


def get_value(name: str, default=None, cast=None):
    return CONFIG.get_value(name, default=default, cast=cast)


def reload_config() -> None:
    """Lädt config.json neu (z. B. vor jedem main.py-Durchlauf oder in der App)."""
    CONFIG.reload()


def update_runtime_settings(new_settings: dict) -> None:
    return CONFIG.update_runtime_settings(new_settings)


def update_live_scenario_settings(new_settings: dict) -> None:
    return CONFIG.update_live_scenario_settings(new_settings)


def set_live_scenario_id(scenario_id: str) -> None:
    return CONFIG.set_live_scenario_id(scenario_id)


def update_appliance_defaults(
    appliance_id: str,
    *,
    power_kw: float,
    runtime_h: float,
) -> None:
    return CONFIG.update_appliance_defaults(
        appliance_id, power_kw=power_kw, runtime_h=runtime_h
    )
