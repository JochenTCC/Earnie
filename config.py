# config.py
import os
import json
from dotenv import load_dotenv

# Sensible Daten aus .env laden
load_dotenv()

CONFIG_JSON_PATH = "config.json"


class Config:
    def __init__(
        self,
        config_path: str = CONFIG_JSON_PATH,
        require_loxone_credentials: bool | None = None,
    ):
        self.config_path = config_path
        if require_loxone_credentials is None:
            require_loxone_credentials = os.getenv("ENERGY_OPTIMIZER_OFFLINE") != "1"
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
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Kritischer Fehler: '{self.config_path}' enthält ungültiges JSON: {e}"
            )

    def _get_strict(self, source: dict, keys_path: list) -> any:
        current = source
        for key in keys_path:
            if not isinstance(current, dict) or key not in current:
                raise KeyError(
                    f"Kritischer Konfigurationsfehler: Der Parameter '{'.'.join(keys_path)}' fehlt in {self.config_path}!"
                )
            current = current[key]
        return current

    def _load_env_vars(self) -> None:
        self.LOXONE_IP = os.getenv("LOXONE_IP")
        self.LOXONE_USER = os.getenv("LOXONE_USER")
        self.LOXONE_PASS = os.getenv("LOXONE_PASS")

        if self.require_loxone_credentials and not all([self.LOXONE_IP, self.LOXONE_USER, self.LOXONE_PASS]):
            missing = [k for k in ["LOXONE_IP", "LOXONE_USER", "LOXONE_PASS"] if not os.getenv(k)]
            raise ValueError(
                f"Kritischer Fehler: Fehlende sensible Daten in der .env: {', '.join(missing)}"
            )

    def _load_static_params(self) -> None:
        self.AWATTAR_URL = self._get_strict(self._raw_config, ["awattar", "url"])
        self.FIX_AUFSCHLAG_CENT = self._get_strict(self._raw_config, ["awattar", "fix_aufschlag_cent"])
        self.NETZVERLUST_FAKTOR = self._get_strict(self._raw_config, ["awattar", "netzverlust_faktor"])
        self.MWST_AUSTRIA_FAKTOR = self._get_strict(self._raw_config, ["awattar", "mwst_austria_faktor"])

        self.GLOBAL_TIMEOUT = self._get_strict(self._raw_config, ["system", "global_timeout"])
        self.LOOP_TIMEOUT = self._get_strict(self._raw_config, ["system", "loop_timeout"])

        self.LOXONE_SOC_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "soc_name"])
        self.LOXONE_PV_COUNTER_NAME = self._get_strict(self._raw_config, ["loxone_blocks", "pv_counter_name"])
        self.LOXONE_LOG_FILENAME = self._get_strict(self._raw_config, ["loxone_blocks", "log_filename"])
        self.PV_TUNING_LOG_FILE = self._get_strict(self._raw_config, ["loxone_blocks", "pv_tuning_log_file"])

        loxone_blocks = self._raw_config.get("loxone_blocks", {})
        self.LOXONE_PV_POWER_NAME = loxone_blocks.get("pv_power_name", "Ernie_Live_PV")
        self.LOXONE_BATTERY_POWER_NAME = loxone_blocks.get("battery_power_name", "Ernie_Live_Battery")
        self.LOXONE_GRID_POWER_NAME = loxone_blocks.get("grid_power_name", "Ernie_Live_Grid")

        sim_paths = self._raw_config.get("file_paths_battery_simulation", {})
        self.PATH_CONSUMPTION = sim_paths.get("path_consumption", "")
        self.PATH_CONSUMPTION_TOTAL = self.PATH_CONSUMPTION
        self.PATH_PRODUCTION = sim_paths.get("path_production", "")
        self.PATH_E_AUTO = sim_paths.get("path_e_auto", "")
        self.PATH_POOL = sim_paths.get("path_pool", "")
        self.PATH_WP = sim_paths.get("path_wp", "")
        self.PATH_PRICE = sim_paths.get("path_price", "")
        self.PRICE_SOURCE = sim_paths.get("price_source", "csv")
        self.PRICE_PROVIDER = sim_paths.get("price_provider", "awattar")
        self.PRICE_RANGE = sim_paths.get("price_range", "last_12_months")
        self.ENERGY_CHARTS_BZN = sim_paths.get("energy_charts_bzn", "DE-LU")

        runtime_settings = self._raw_config.get("runtime_settings", {})
        self.WP_NOMINAL_POWER_KW = runtime_settings.get("wp_nominal_power_kw", 1.6)

    def _load_dynamic_params(self) -> None:
        self.K_PUSH_CENT = self._get_strict(self._raw_config, ["runtime_settings", "k_push_cent"])
        self.PV_TILT = self._get_strict(self._raw_config, ["runtime_settings", "pv_tilt"])
        self.PV_AZIMUTH = self._get_strict(self._raw_config, ["runtime_settings", "pv_azimuth"])
        self.PV_KWP = self._get_strict(self._raw_config, ["runtime_settings", "pv_kwp"])

        self.BATTERY_MAX_POWER_KW = self._get_strict(self._raw_config, ["runtime_settings", "battery_max_power_kw"])
        self.BATTERY_EFFICIENCY = self._get_strict(self._raw_config, ["runtime_settings", "battery_efficiency"])
        self.BATTERY_CAPACITY_KWH = self._get_strict(self._raw_config, ["runtime_settings", "battery_capacity_kwh"])
        self.BATTERY_MIN_SOC = self._get_strict(self._raw_config, ["runtime_settings", "battery_min_soc"])
        self.BATTERY_MAX_SOC = self._get_strict(self._raw_config, ["runtime_settings", "battery_max_soc"])

        self.LATITUDE = self._get_strict(self._raw_config, ["runtime_settings", "latitude"])
        self.LONGITUDE = self._get_strict(self._raw_config, ["runtime_settings", "longitude"])

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
        }

    def get_battery_params(self) -> dict:
        return {
            'battery_capacity_kwh': self.get('BATTERY_CAPACITY_KWH', cast=float),
            'min_soc': self.get('BATTERY_MIN_SOC', cast=float),
            'max_soc': self.get('BATTERY_MAX_SOC', cast=float),
            'max_power_kw': self.get('BATTERY_MAX_POWER_KW', cast=float),
            'efficiency': self.get('BATTERY_EFFICIENCY', cast=float),
        }

    def get_push_price_cent(self) -> float:
        return self.get('K_PUSH_CENT', cast=float)

    def get_global_timeout(self, default: int = 5) -> int:
        return self.get('GLOBAL_TIMEOUT', default=default, cast=int)

    def get_file_paths_battery_simulation(self) -> dict:
        """Gibt den Block file_paths_battery_simulation aus der JSON-Struktur zurück."""
        return {
            "path_consumption": self.PATH_CONSUMPTION,
            "path_production": self.PATH_PRODUCTION,
            "path_e_auto": self.PATH_E_AUTO,
            "path_pool": self.PATH_POOL,
            "path_wp": self.PATH_WP,
            "path_price": self.PATH_PRICE,
            "price_source": self.PRICE_SOURCE,
            "price_provider": self.PRICE_PROVIDER,
            "price_range": self.PRICE_RANGE,
            "energy_charts_bzn": self.ENERGY_CHARTS_BZN,
        }

    def get_scenario_settings(self) -> dict:
        """Lädt alle Szenario-Blöcke (z. B. scenario_settings_1, scenario_settings_2)."""
        return {
            key: value
            for key, value in self._raw_config.items()
            if key.startswith("scenario_settings")
        }

    def get_value(self, name: str, default=None, cast=None):
        return self.get(name, default=default, cast=cast)

    def reload(self) -> None:
        self._load_all()

    def update_runtime_settings(self, new_settings: dict) -> None:
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

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

            data["runtime_settings"][target_key] = value
            setattr(self, target_key.upper(), value)

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        self._raw_config = data
        self._load_dynamic_params()


CONFIG = Config()


def get(name: str, default=None, cast=None):
    return CONFIG.get(name, default=default, cast=cast)


def get_runtime_settings() -> dict:
    return CONFIG.get_runtime_settings()


def get_battery_params() -> dict:
    return CONFIG.get_battery_params()


def get_push_price_cent() -> float:
    return CONFIG.get_push_price_cent()


def get_global_timeout(default: int = 5) -> int:
    return CONFIG.get_global_timeout(default=default)


def get_file_paths_battery_simulation() -> dict:
    return CONFIG.get_file_paths_battery_simulation()


def get_scenario_settings() -> dict:
    return CONFIG.get_scenario_settings()


def get_value(name: str, default=None, cast=None):
    return CONFIG.get_value(name, default=default, cast=cast)


def update_runtime_settings(new_settings: dict) -> None:
    return CONFIG.update_runtime_settings(new_settings)