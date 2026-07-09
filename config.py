# config.py
import os
import json

from runtime_store.dotenv_io import loxone_credentials_configured
from runtime_store.dotenv_loader import load_app_dotenv

# Sensible Daten aus .env laden (Prod: config/.env, Dev: Fallback ./.env)
load_app_dotenv()

from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_config_json_path,
    resolve_dotenv_path,
    resolve_house_profiles_json_path,
    resolve_local_settings_json_path,
    resolve_tariffs_json_path,
)
from settings import appliances as appliance_settings
from settings import flexible_consumers as fc_settings
from settings import scenarios as scenario_settings
from settings import system_settings
from settings.json_io import read_json_dict, write_json_dict

CONFIG_JSON_PATH = resolve_config_json_path()
BACKTESTING_SCENARIOS_JSON_PATH = resolve_backtesting_scenarios_json_path()
LOCAL_SETTINGS_JSON_PATH = resolve_local_settings_json_path()
TARIFFS_JSON_PATH = resolve_tariffs_json_path()
HOUSE_PROFILES_JSON_PATH = resolve_house_profiles_json_path()


def _default_require_loxone_credentials() -> bool:
    if os.getenv("ENERGY_OPTIMIZER_OFFLINE") == "1":
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

    def __init__(
        self,
        config_path: str = CONFIG_JSON_PATH,
        backtesting_scenarios_path: str = BACKTESTING_SCENARIOS_JSON_PATH,
        local_settings_path: str = LOCAL_SETTINGS_JSON_PATH,
        tariffs_path: str = TARIFFS_JSON_PATH,
        house_profiles_path: str = HOUSE_PROFILES_JSON_PATH,
        require_loxone_credentials: bool | None = None,
    ):
        self.config_path = config_path
        self.backtesting_scenarios_path = backtesting_scenarios_path
        self.local_settings_path = local_settings_path
        self.tariffs_path = tariffs_path
        self.house_profiles_path = house_profiles_path
        if require_loxone_credentials is None:
            require_loxone_credentials = _default_require_loxone_credentials()
        self.require_loxone_credentials = require_loxone_credentials
        self._raw_config = None
        self._load_all()

    def _load_all(self) -> None:
        self._raw_config = self._load_json()
        self._load_env_vars()
        self._load_static_params()
        self._load_dynamic_params()

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

    def _get_strict(self, source: dict, keys_path: list) -> any:
        current = source
        for key in keys_path:
            if not isinstance(current, dict) or key not in current:
                raise KeyError(
                    f"Kritischer Konfigurationsfehler: Der Parameter '{'.'.join(keys_path)}' fehlt in {self.config_path}!"
                )
            current = current[key]
        return current

    @staticmethod
    def _validate_threshold_power(value) -> float:
        rel = float(value)
        if rel <= 0.0 or rel > 1.0:
            raise ValueError(
                "Kritischer Konfigurationsfehler: runtime_settings.threshold_power "
                "muss ein relativer Anteil zwischen 0 (exklusiv) und 1 (inklusiv) sein."
            )
        return rel

    def _load_local_settings_document(self) -> dict:
        path = self.local_settings_path
        if not os.path.isfile(path):
            return {}
        try:
            return read_json_dict(path)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Kritischer Fehler: '{path}' enthält ungültiges JSON: {e}"
            ) from e

    def _load_event_triggers(self) -> list[dict]:
        return system_settings.load_event_triggers(self._raw_config)

    def _load_env_vars(self) -> None:
        self.LOXONE_IP = os.getenv("LOXONE_IP")
        self.LOXONE_USER = os.getenv("LOXONE_USER")
        self.LOXONE_PASS = os.getenv("LOXONE_PASS")

        if self.require_loxone_credentials and not all([self.LOXONE_IP, self.LOXONE_USER, self.LOXONE_PASS]):
            missing = [k for k in ["LOXONE_IP", "LOXONE_USER", "LOXONE_PASS"] if not os.getenv(k)]
            dotenv_path = resolve_dotenv_path()
            raise ValueError(
                f"Kritischer Fehler: Fehlende sensible Daten in '{dotenv_path}': "
                f"{', '.join(missing)}"
            )

    def _load_static_params(self) -> None:
        self.AWATTAR_URL = self._get_strict(self._raw_config, ["awattar", "url"])
        self.FIX_AUFSCHLAG_CENT = self._get_strict(self._raw_config, ["awattar", "fix_aufschlag_cent"])
        self.NETZVERLUST_FAKTOR = self._get_strict(self._raw_config, ["awattar", "netzverlust_faktor"])
        self.MWST_AUSTRIA_FAKTOR = self._get_strict(self._raw_config, ["awattar", "mwst_austria_faktor"])

        self.GLOBAL_TIMEOUT = self._get_strict(self._raw_config, ["system", "global_timeout"])
        self.LOOP_TIMEOUT = self._get_strict(self._raw_config, ["system", "loop_timeout"])
        local_settings = self._load_local_settings_document()
        self.LOXONE_SILENT_MODE = system_settings.load_loxone_silent_mode(
            self._raw_config,
            local_settings,
            self.local_settings_path,
        )
        self.EVENT_TRIGGER_ENABLED = system_settings.load_event_trigger_enabled(self._raw_config)
        self.EVENT_POLL_INTERVAL_SEC = system_settings.load_event_poll_interval_sec(self._raw_config)
        self.EVENT_TRIGGERS = self._load_event_triggers()
        self.UI_FRAGMENT_REFRESH_CHARTS_SEC = system_settings.load_ui_fragment_refresh_sec(
            self._raw_config,
            "fragment_refresh_charts_sec",
            60,
        )
        self.UI_FRAGMENT_REFRESH_STATUS_SEC = system_settings.load_ui_fragment_refresh_sec(
            self._raw_config,
            "fragment_refresh_status_sec",
            10,
        )
        self.UI_MAIN_SYNC_POLL_SEC = system_settings.load_ui_fragment_refresh_sec(
            self._raw_config,
            "main_sync_poll_sec",
            15,
        )
        self.UI_CHART_DEBUG_CAPTURE_ENABLED = system_settings.load_ui_bool(
            self._raw_config,
            "chart_debug_capture_enabled",
            False,
        )
        self.UI_CHART_DEBUG_CAPTURE_DIR = system_settings.load_ui_chart_debug_capture_dir(
            self._raw_config
        )
        self.UI_STREAMLIT_PORT = system_settings.load_ui_streamlit_port(self._raw_config)
        self.UI_PRICE_FORECAST_PAGE_ENABLED = system_settings.load_ui_bool(
            self._raw_config,
            "price_forecast_page_enabled",
            False,
        )

        self.LOXONE_SOC_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "soc_name"])
        self.LOXONE_PV_COUNTER_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "pv_counter_name"])
        self.LOXONE_LOG_FILENAME = self._get_strict(self._raw_config, ["loxone_blocks", "log_filename"])
        self.PV_TUNING_LOG_FILE = self._get_strict(self._raw_config, ["loxone_blocks", "pv_tuning_log_file"])
        self.LOXONE_PV_POWER_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "pv_power_name"])
        self.LOXONE_BATTERY_POWER_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "battery_power_name"])
        self.LOXONE_GRID_POWER_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "grid_power_name"])
        self.LOXONE_TARGET_SOC_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "target_soc_name"])
        self.LOXONE_TARGET_CHARGE_POWER_NAME = self._get_strict(
            self._raw_config, ["loxone_blocks", "target_charge_power_name"]
        )
        self.LOXONE_TARGET_DISCHARGE_POWER_NAME = self._get_strict(
            self._raw_config, ["loxone_blocks", "target_discharge_power_name"]
        )
        self.LOXONE_CONTROL_CMD_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "control_cmd_name"])

        sim_paths = self._raw_config.get("file_paths_battery_simulation", {})
        self.PATH_CONSUMPTION = sim_paths.get("path_consumption", "")
        self.PATH_CONSUMPTION_TOTAL = self.PATH_CONSUMPTION
        self.PATH_PRODUCTION = sim_paths.get("path_production", "")
        self.PATH_PRICE = sim_paths.get("path_price", "")
        self.PATH_CONS_DATA = sim_paths.get("path_cons_data", "runtime/cons_data_hourly.csv")
        self.CONS_DATA_RETENTION_MONTHS = sim_paths.get("cons_data_retention_months", 24)
        self.CONS_DATA_WRITE_MODE = sim_paths.get("cons_data_write_mode", "hourly")
        self.PRICE_SOURCE = sim_paths.get("price_source", "csv")
        self.PRICE_PROVIDER = sim_paths.get("price_provider", "awattar")
        self.PRICE_RANGE = sim_paths.get("price_range", "last_12_months")
        self.ENERGY_CHARTS_BZN = sim_paths.get("energy_charts_bzn", "DE-LU")

        # Legacy-Pfad-Aliase aus flexible_consumers (Abwärtskompatibilität)
        self.PATH_E_AUTO = self._consumer_path("eauto")
        self.PATH_POOL = self._consumer_path("swimspa")
        self.PATH_WP = self._consumer_path("waermepumpe")
        wp_consumer = self._consumer_by_id("waermepumpe")
        self.WP_NOMINAL_POWER_KW = float(wp_consumer.get("nominal_power_kw", 1.6)) if wp_consumer else 1.6

    def _consumer_by_id(self, consumer_id: str) -> dict | None:
        return fc_settings.consumer_by_id(self._raw_config, consumer_id)

    def _consumer_path(self, consumer_id: str, default: str = "") -> str:
        return fc_settings.consumer_path(self._raw_config, consumer_id, default)

    def _load_dynamic_params(self) -> None:
        self.K_PUSH_CENT = self._get_strict(self._raw_config, ["runtime_settings", "k_push_cent"])
        feed_in_mode_raw = self._raw_config.get("runtime_settings", {}).get("feed_in_mode")
        if feed_in_mode_raw is None:
            self.FEED_IN_MODE = "fixed"
        else:
            from data.feed_in_prices import validate_feed_in_mode

            self.FEED_IN_MODE = validate_feed_in_mode(feed_in_mode_raw)
        self.PV_TILT = self._get_strict(self._raw_config, ["runtime_settings", "pv_tilt"])
        self.PV_AZIMUTH = self._get_strict(self._raw_config, ["runtime_settings", "pv_azimuth"])
        self.PV_KWP = self._get_strict(self._raw_config, ["runtime_settings", "pv_kwp"])

        self.BATTERY_MAX_POWER_KW = self._get_strict(self._raw_config, ["runtime_settings", "battery_max_power_kw"])
        self.BATTERY_EFFICIENCY = self._get_strict(self._raw_config, ["runtime_settings", "battery_efficiency"])
        self.BATTERY_CAPACITY_KWH = self._get_strict(self._raw_config, ["runtime_settings", "battery_capacity_kwh"])
        self.BATTERY_MIN_SOC = self._get_strict(self._raw_config, ["runtime_settings", "battery_min_soc"])
        self.BATTERY_MAX_SOC = self._get_strict(self._raw_config, ["runtime_settings", "battery_max_soc"])
        self.THRESHOLD_POWER = self._validate_threshold_power(
            self._get_strict(self._raw_config, ["runtime_settings", "threshold_power"])
        )

        self.LATITUDE = self._get_strict(self._raw_config, ["runtime_settings", "latitude"])
        self.LONGITUDE = self._get_strict(self._raw_config, ["runtime_settings", "longitude"])
        self.PLANNING_TIMEZONE = self._get_strict(
            self._raw_config, ["runtime_settings", "timezone_name"]
        )
        planning_raw = self._raw_config.get("planning_horizon", {})
        if not isinstance(planning_raw, dict):
            raise ValueError(
                "Kritischer Konfigurationsfehler: Block 'planning_horizon' ist ungültig."
            )
        mode_raw = planning_raw.get("mode")
        if mode_raw is None:
            raise ValueError(
                "Kritischer Konfigurationsfehler: planning_horizon.mode fehlt in config.json."
            )
        self.PLANNING_HORIZON_MODE = str(mode_raw)

    def get_planning_timezone(self) -> str:
        return str(self.PLANNING_TIMEZONE)

    def is_sunset_planning_horizon(self) -> bool:
        if self.PLANNING_HORIZON_MODE != "sunset_window":
            raise ValueError(
                "Unbekannter planning_horizon.mode "
                f"'{self.PLANNING_HORIZON_MODE}' — erwartet 'sunset_window'."
            )
        return True

    def get(self, name: str, default=None, cast=None):
        value = getattr(self, name, default)
        if value is None:
            value = default
        return cast(value) if cast and value is not None else value

    def get_runtime_settings(self) -> dict:
        return {
            'PV_KWP': self.get('PV_KWP', cast=float),
            'PV_TILT': self.get('PV_TILT', cast=float),
            'PV_AZIMUTH': self.get('PV_AZIMUTH', cast=float),
            'K_PUSH_CENT': self.get('K_PUSH_CENT', cast=float),
            'BATTERY_CAPACITY_KWH': self.get('BATTERY_CAPACITY_KWH', cast=float),
            'BATTERY_MIN_SOC': self.get('BATTERY_MIN_SOC', cast=float),
            'BATTERY_MAX_SOC': self.get('BATTERY_MAX_SOC', cast=float),
            'BATTERY_MAX_POWER_KW': self.get('BATTERY_MAX_POWER_KW', cast=float),
            'THRESHOLD_POWER': self.get('THRESHOLD_POWER', cast=float),
        }

    def get_battery_params(self) -> dict:
        return {
            'battery_capacity_kwh': self.get('BATTERY_CAPACITY_KWH', cast=float),
            'min_soc': self.get('BATTERY_MIN_SOC', cast=float),
            'max_soc': self.get('BATTERY_MAX_SOC', cast=float),
            'max_power_kw': self.get('BATTERY_MAX_POWER_KW', cast=float),
            'efficiency': self.get('BATTERY_EFFICIENCY', cast=float),
        }

    def get_flexible_consumers(self, optimizer_only: bool = False) -> list:
        """Lädt alle konfigurierten flexiblen Verbraucher."""
        consumers = [
            fc_settings.normalize_consumer(raw)
            for raw in self._raw_config.get("flexible_consumers", [])
        ]
        if optimizer_only:
            return [
                c for c in consumers
                if c["optimizer_enabled"]
                and c["nominal_power_kw"] > 0
                and fc_settings.consumer_has_daily_target(c)
            ]
        return consumers

    def get_appliances(self) -> list[dict]:
        """Manuelle Geräte für den Empfehlungsmodus (rein beratend, kein MILP)."""
        return appliance_settings.normalize_appliance_list(
            self._raw_config.get("appliances", [])
        )

    def update_appliance_defaults(
        self,
        appliance_id: str,
        *,
        power_kw: float,
        runtime_h: float,
    ) -> None:
        """Persistiert Nennleistung und Laufzeit-Vorbelegung für ein manuelles Gerät."""
        self._raw_config = appliance_settings.update_appliance_defaults_in_file(
            self.config_path,
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

    def get_eauto_milp_params(self) -> dict[str, float]:
        """Pflichtparameter für E-Auto MILP Modus A/B und Tie-Break."""
        from optimizer.eauto_milp import validate_eauto_milp_params

        return validate_eauto_milp_params(self._raw_config.get("eauto_milp"))

    def get_battery_wear_cent_per_kwh(self, capacity_kwh: float) -> float:
        """Verschleiß ct/kWh Durchsatz für MILP; 0 wenn battery_wear.enabled=false."""
        from optimizer.battery_wear import (
            battery_wear_cent_per_kwh_from_config,
            validate_battery_wear_config,
        )

        wear = validate_battery_wear_config(self._raw_config.get("battery_wear"))
        return battery_wear_cent_per_kwh_from_config(wear, float(capacity_kwh))

    def get_swimspa_settings(self) -> dict:
        """Legacy-Hilfsfunktion: liefert den SwimSpa-Verbraucher oder Defaults."""
        consumer = self._consumer_by_id("swimspa")
        if consumer:
            return {
                "nominal_power_kw": consumer["nominal_power_kw"],
                "daily_target_kwh": consumer["daily_target_kwh"],
            }
        return {"nominal_power_kw": 2.8, "daily_target_kwh": 10.0}

    def get_push_price_cent(self) -> float:
        return self.get('K_PUSH_CENT', cast=float)

    def get_feed_in_settings(self, runtime_override: dict | None = None):
        from data.feed_in_prices import feed_in_settings_from_dict

        runtime = runtime_override if runtime_override is not None else self._raw_config["runtime_settings"]
        awattar = self._raw_config.get("awattar", {})
        return feed_in_settings_from_dict(runtime, awattar)

    def get_backtesting_fixed_monthly_feed_in_rates(
        self,
    ) -> tuple[tuple[int, int, float], ...] | None:
        from data.feed_in_prices import validate_fixed_monthly_feed_in_rates

        raw = self._load_backtesting_scenarios_document().get("fixed_monthly_feed_in_rates")
        if raw is None:
            return None
        return validate_fixed_monthly_feed_in_rates(raw)

    def get_backtesting_feed_in_settings(self, runtime_override: dict | None = None):
        """Einspeise-Settings für Backtesting inkl. monatlicher Fixtarife."""
        from data.feed_in_prices import FEED_IN_MODE_FIXED, feed_in_settings_from_dict, validate_feed_in_mode
        from data.monthly_float_rates import (
            build_monthly_float_lookup,
            load_monthly_float_reference_cent,
            load_oemag_monthly_reference_rates,
        )

        runtime = runtime_override if runtime_override is not None else self._raw_config["runtime_settings"]
        awattar = self._raw_config.get("awattar", {})
        monthly = None
        export_spec = runtime.get("_export_tariff_spec")
        export_type = str(export_spec.get("type", "")).strip().lower() if export_spec else ""
        if export_type == "monthly_float":
            scenarios_doc = self._load_backtesting_scenarios_document()
            oemag_rates = load_oemag_monthly_reference_rates(scenarios_doc)
            reference_cent = load_monthly_float_reference_cent(scenarios_doc)
            monthly = build_monthly_float_lookup(oemag_rates, reference_cent, export_spec)
        elif runtime_override and runtime_override.get("_monthly_fixed_tariffs") is not None:
            monthly = runtime_override["_monthly_fixed_tariffs"]
        elif validate_feed_in_mode(runtime.get("feed_in_mode", FEED_IN_MODE_FIXED)) == FEED_IN_MODE_FIXED:
            monthly = self.get_backtesting_fixed_monthly_feed_in_rates()
        return feed_in_settings_from_dict(
            runtime,
            awattar,
            monthly_fixed_tariffs=monthly,
        )

    def get_threshold_power(self) -> float:
        """Relativer Leistungsschwellenwert (Anteil von battery_max_power_kw)."""
        return self.get('THRESHOLD_POWER', cast=float)

    def get_global_timeout(self, default: int = 5) -> int:
        return self.get('GLOBAL_TIMEOUT', default=default, cast=int)

    def is_loxone_silent_mode(self) -> bool:
        return bool(self.get('LOXONE_SILENT_MODE', default=False))

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
        return bool(self.get("UI_CHART_DEBUG_CAPTURE_ENABLED", default=False))

    def get_ui_chart_debug_capture_dir(self) -> str:
        return str(self.get("UI_CHART_DEBUG_CAPTURE_DIR", default="chart_debug"))

    def get_ui_streamlit_port(self) -> int:
        return int(self.get("UI_STREAMLIT_PORT", default=8501))

    def get_ui_price_forecast_page_enabled(self) -> bool:
        return bool(self.get("UI_PRICE_FORECAST_PAGE_ENABLED", default=False))

    def get_event_triggers(self) -> list[dict]:
        return list(self.EVENT_TRIGGERS)

    def get_file_paths_battery_simulation(self) -> dict:
        """Gibt den Block file_paths_battery_simulation aus der JSON-Struktur zurück."""
        return {
            "path_consumption": self.PATH_CONSUMPTION,
            "path_production": self.PATH_PRODUCTION,
            "path_price": self.PATH_PRICE,
            "path_cons_data": self.PATH_CONS_DATA,
            "cons_data_retention_months": self.CONS_DATA_RETENTION_MONTHS,
            "cons_data_write_mode": self.CONS_DATA_WRITE_MODE,
            "price_source": self.PRICE_SOURCE,
            "price_provider": self.PRICE_PROVIDER,
            "price_range": self.PRICE_RANGE,
            "energy_charts_bzn": self.ENERGY_CHARTS_BZN,
        }

    def get_scenario_settings(self) -> dict:
        """Lädt Szenario-Parameter als {id: settings}-Dict (Abwärtskompatibilität)."""
        return {scenario["id"]: scenario["settings"] for scenario in self.get_scenarios()}

    def _load_backtesting_scenarios_document(self) -> dict:
        return scenario_settings.load_backtesting_scenarios_document(
            self.backtesting_scenarios_path
        )

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
        """Anzeigenamen für Backtesting-Szenarien (runtime_settings = Baseline)."""
        labels = {"runtime_settings": "Runtime (Baseline)"}
        for scenario in self.get_scenarios():
            labels[scenario["id"]] = scenario["label"]
        return labels

    def get_batteries(self) -> list[dict]:
        from house_config.entity_resolution import batteries_by_id

        return list(batteries_by_id(self._raw_config).values())

    def get_pv_systems(self) -> list[dict]:
        from house_config.entity_resolution import pv_systems_by_id

        return list(pv_systems_by_id(self._raw_config).values())

    def resolve_scenario_settings_dict(self, settings: dict) -> dict:
        from house_config.scenario_resolution import resolve_scenario_settings

        holder: dict = {}
        resolved = resolve_scenario_settings(
            settings,
            raw_config=self._raw_config,
            tariffs_path=self.tariffs_path,
            house_profiles_path=self.house_profiles_path,
            monthly_rates_holder=holder,
        )
        if holder.get("_monthly_fixed_tariffs") is not None:
            resolved["_monthly_fixed_tariffs"] = holder["_monthly_fixed_tariffs"]
        return resolved

    def get_backtesting_scenarios(self) -> dict[str, dict]:
        """runtime_settings als Baseline, gefolgt von aufgelösten Szenarien."""
        from house_config.scenario_resolution import resolve_runtime_settings_for_backtesting

        baseline_holder: dict = {}
        baseline = resolve_runtime_settings_for_backtesting(
            self._raw_config,
            tariffs_path=self.tariffs_path,
            house_profiles_path=self.house_profiles_path,
            monthly_rates_holder=baseline_holder,
        )
        if baseline_holder.get("_monthly_fixed_tariffs") is not None:
            baseline["_monthly_fixed_tariffs"] = baseline_holder["_monthly_fixed_tariffs"]
        scenarios = {"runtime_settings": baseline}
        for scenario in self.get_scenarios():
            scenarios[scenario["id"]] = self.resolve_scenario_settings_dict(scenario["settings"])
        return scenarios

    def get_value(self, name: str, default=None, cast=None):
        return self.get(name, default=default, cast=cast)

    def reload(self) -> None:
        self._load_all()

    def update_runtime_settings(self, new_settings: dict) -> None:
        data = read_json_dict(self.config_path)

        for key, value in new_settings.items():
            target_key = None
            for json_key in data["runtime_settings"].keys():
                if json_key.lower() == key.lower():
                    target_key = json_key
                    break

            if target_key is None:
                raise KeyError(
                    f"Sicherheitsfehler: '{key}' ist kein konfigurierbarer Laufzeit-Parameter!"
                )

            if target_key == "threshold_power":
                value = self._validate_threshold_power(value)

            data["runtime_settings"][target_key] = value
            setattr(self, target_key.upper(), value)

        write_json_dict(self.config_path, data)

        self._raw_config = data
        self._load_dynamic_params()


CONFIG = Config(require_loxone_credentials=_default_require_loxone_credentials())


def reinit_config(require_loxone_credentials: bool | None = None) -> None:
    """Lädt die Konfiguration neu (z. B. nach Bootstrap mit neu angelegter config.json)."""
    global CONFIG, CONFIG_JSON_PATH, BACKTESTING_SCENARIOS_JSON_PATH, LOCAL_SETTINGS_JSON_PATH
    global TARIFFS_JSON_PATH, HOUSE_PROFILES_JSON_PATH
    CONFIG_JSON_PATH = resolve_config_json_path()
    BACKTESTING_SCENARIOS_JSON_PATH = resolve_backtesting_scenarios_json_path()
    LOCAL_SETTINGS_JSON_PATH = resolve_local_settings_json_path()
    TARIFFS_JSON_PATH = resolve_tariffs_json_path()
    HOUSE_PROFILES_JSON_PATH = resolve_house_profiles_json_path()
    if require_loxone_credentials is None:
        require_loxone_credentials = _default_require_loxone_credentials()
    CONFIG = Config(
        config_path=CONFIG_JSON_PATH,
        backtesting_scenarios_path=BACKTESTING_SCENARIOS_JSON_PATH,
        local_settings_path=LOCAL_SETTINGS_JSON_PATH,
        tariffs_path=TARIFFS_JSON_PATH,
        house_profiles_path=HOUSE_PROFILES_JSON_PATH,
        require_loxone_credentials=require_loxone_credentials,
    )


def get(name: str, default=None, cast=None):
    return CONFIG.get(name, default=default, cast=cast)


def get_runtime_settings() -> dict:
    return CONFIG.get_runtime_settings()


def get_battery_params() -> dict:
    return CONFIG.get_battery_params()


def get_swimspa_settings() -> dict:
    return CONFIG.get_swimspa_settings()


def get_flexible_consumers(optimizer_only: bool = False) -> list:
    return CONFIG.get_flexible_consumers(optimizer_only=optimizer_only)


def get_appliances() -> list[dict]:
    return CONFIG.get_appliances()


def get_appliance_recommendation_settings() -> dict:
    return CONFIG.get_appliance_recommendation_settings()


def update_appliance_recommendation_settings(new_settings: dict) -> None:
    return CONFIG.update_appliance_recommendation_settings(new_settings)


def get_eauto_milp_params() -> dict[str, float]:
    return CONFIG.get_eauto_milp_params()


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


def is_sunset_planning_horizon() -> bool:
    return CONFIG.is_sunset_planning_horizon()


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


def get_file_paths_battery_simulation() -> dict:
    return CONFIG.get_file_paths_battery_simulation()


def get_scenario_settings() -> dict:
    return CONFIG.get_scenario_settings()


def get_scenarios() -> list[dict]:
    return CONFIG.get_scenarios()


def get_scenario_labels() -> dict[str, str]:
    return CONFIG.get_scenario_labels()


def get_backtesting_scenarios() -> dict[str, dict]:
    return CONFIG.get_backtesting_scenarios()


def get_batteries() -> list[dict]:
    return CONFIG.get_batteries()


def get_pv_systems() -> list[dict]:
    return CONFIG.get_pv_systems()


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


def update_appliance_defaults(
    appliance_id: str,
    *,
    power_kw: float,
    runtime_h: float,
) -> None:
    return CONFIG.update_appliance_defaults(
        appliance_id, power_kw=power_kw, runtime_h=runtime_h
    )
