# config.py
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# Sensible Daten aus .env laden
load_dotenv()

from runtime_store.persist_paths import resolve_config_json_path

CONFIG_JSON_PATH = resolve_config_json_path()


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

    @staticmethod
    def _read_json_dict(path: str) -> dict:
        """Liest JSON mit UTF-8; Fallback cp1252 (häufig bei manueller Bearbeitung auf Windows/Synology)."""
        last_decode_error: UnicodeDecodeError | None = None
        for encoding in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                with open(path, "r", encoding=encoding) as f:
                    return json.load(f)
            except UnicodeDecodeError as e:
                last_decode_error = e
            except json.JSONDecodeError:
                raise
        raise ValueError(
            f"Konfigurationsdatei '{path}' ist weder UTF-8 noch cp1252 "
            f"(z. B. Umlaute wie in 'Wärmepumpe'). Bitte als UTF-8 speichern."
        ) from last_decode_error

    def _load_json(self) -> dict:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(
                f"Kritischer Fehler: Die Konfigurationsdatei '{self.config_path}' wurde nicht gefunden!"
            )

        try:
            return self._read_json_dict(self.config_path)
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
        for raw in self._raw_config.get("flexible_consumers", []):
            if raw.get("id") == consumer_id:
                return self._normalize_consumer(raw)
        return None

    def _consumer_path(self, consumer_id: str, default: str = "") -> str:
        consumer = self._consumer_by_id(consumer_id)
        return consumer.get("path_log", default) if consumer else default

    @staticmethod
    def _normalize_day_schedule(block: dict | None) -> dict:
        if not isinstance(block, dict):
            return {}
        out = {}
        available = block.get("car_available_from_hour", block.get("charge_from_hour"))
        ready = block.get("ready_by_hour", block.get("charge_until_hour"))
        if available is not None:
            out["car_available_from_hour"] = int(available) % 24
        if ready is not None:
            out["ready_by_hour"] = int(ready) % 24
        if block.get("daily_rest_soc") is not None:
            out["daily_rest_soc"] = float(block["daily_rest_soc"])
        return out

    @staticmethod
    def _charging_efficiency(sched: dict) -> float:
        """Lade-Wirkungsgrad (Netz-/Zählerenergie → Akku); Default 0,95 wenn nicht gesetzt."""
        raw = sched.get("charging_efficiency")
        if raw is None:
            return 0.90
        efficiency = float(raw)
        if efficiency <= 0.0 or efficiency > 1.0:
            raise ValueError(
                "charging_schedule.charging_efficiency muss ein Wert zwischen 0 (exklusiv) "
                "und 1 (inklusiv) sein."
            )
        return efficiency

    @staticmethod
    def target_kwh_from_rest_soc(consumer: dict, rest_soc_percent: float | None) -> float | None:
        """Berechnet Ladeziel (kWh) aus Rest-SOC (%), Kapazität und Lade-Wirkungsgrad."""
        if rest_soc_percent is None:
            return None
        sched = consumer.get("charging_schedule") or {}
        capacity = float(sched.get("battery_capacity_kwh", 0.0) or 0.0)
        if capacity <= 0:
            return None
        target_soc = float(sched.get("target_soc_percent", 100.0) or 100.0)
        battery_delta_kwh = (target_soc - float(rest_soc_percent)) / 100.0 * capacity
        efficiency = Config._charging_efficiency(sched)
        return max(0.0, battery_delta_kwh / efficiency)

    @staticmethod
    def target_kwh_from_day_schedule(consumer: dict, when: datetime) -> float | None:
        """Ladeziel (kWh) aus daily_rest_soc des passenden Wochentags in charging_schedule."""
        sched = consumer.get("charging_schedule")
        if not sched or not sched.get("enabled"):
            return None
        day_key = "weekend" if when.weekday() >= 5 else "weekday"
        rest_soc = (sched.get(day_key) or {}).get("daily_rest_soc")
        return Config.target_kwh_from_rest_soc(consumer, rest_soc)

    @staticmethod
    def _normalize_loxone_outputs(raw: dict | None) -> dict:
        if not isinstance(raw, dict):
            return {}
        enable_name = str(raw.get("enable_name", "")).strip()
        return {"enable_name": enable_name} if enable_name else {}

    @staticmethod
    def _normalize_loxone_inputs(raw: dict | None) -> dict:
        """Live-Messwerte aus Loxone (cons_data / Monitoring)."""
        if not isinstance(raw, dict):
            return {}
        power_name = str(raw.get("power_name", "")).strip()
        return {"power_name": power_name} if power_name else {}

    @staticmethod
    def _normalize_charging_schedule(raw: dict | None) -> dict | None:
        if not raw or not bool(raw.get("enabled", False)):
            return None
        loxone = {}
        if isinstance(raw.get("loxone"), dict):
            for key in (
                "plugged_in_name",
                "ready_by_time_name",
                "soc_at_plug_in_name",
                "nominal_power_kw_name",
                "charge_enable_name",
            ):
                if raw["loxone"].get(key):
                    loxone[key] = str(raw["loxone"][key]).strip()
        charging_efficiency = raw.get("charging_efficiency")
        normalized_efficiency = (
            Config._charging_efficiency({"charging_efficiency": charging_efficiency})
            if charging_efficiency is not None
            else 0.95
        )
        return {
            "enabled": True,
            "forecast_when_absent": bool(raw.get("forecast_when_absent", False)),
            "battery_capacity_kwh": float(raw.get("battery_capacity_kwh", 0.0) or 0.0),
            "target_soc_percent": float(raw.get("target_soc_percent", 100.0) or 100.0),
            "charging_efficiency": normalized_efficiency,
            "weekday": Config._normalize_day_schedule(raw.get("weekday")),
            "weekend": Config._normalize_day_schedule(raw.get("weekend")),
            "loxone": loxone,
        }

    @staticmethod
    def _normalize_consumer(raw: dict) -> dict:
        source = str(raw.get("daily_target_source", "config")).lower().strip()
        if "daily_target_source" not in raw:
            charging_raw = raw.get("charging_schedule")
            if isinstance(charging_raw, dict) and charging_raw.get("source"):
                legacy = str(charging_raw["source"]).lower().strip()
                if legacy in ("config", "historical", "loxone"):
                    source = legacy
        if source not in ("config", "historical", "loxone"):
            source = "config"
        loxone_outputs = Config._normalize_loxone_outputs(raw.get("loxone_outputs"))
        charging_schedule = Config._normalize_charging_schedule(raw.get("charging_schedule"))
        if not loxone_outputs and charging_schedule:
            sched_lox = charging_schedule.get("loxone") or {}
            if sched_lox.get("charge_enable_name"):
                loxone_outputs = {"enable_name": sched_lox["charge_enable_name"]}
        return {
            "id": str(raw["id"]),
            "name": str(raw.get("name", raw["id"])),
            "nominal_power_kw": float(raw.get("nominal_power_kw", 0.0)),
            "daily_target_kwh": float(raw.get("daily_target_kwh", 0.0)),
            "daily_target_source": source,
            "loxone_target_kwh_name": str(raw.get("loxone_target_kwh_name", "")).strip(),
            "min_on_quarterhours": max(1, int(raw.get("min_on_quarterhours", raw.get("min_on_hours", 1) * 4))),
            "path_log": str(raw.get("path_log", "")),
            "signal_type": str(raw.get("signal_type", "power")),
            "log_signal_type": str(
                raw.get("log_signal_type") or raw.get("signal_type", "power")
            ),
            "optimizer_enabled": bool(raw.get("optimizer_enabled", True)),
            "loxone_outputs": loxone_outputs,
            "loxone_inputs": Config._normalize_loxone_inputs(raw.get("loxone_inputs")),
            "charging_schedule": charging_schedule,
        }

    @staticmethod
    def _consumer_has_daily_target(consumer: dict) -> bool:
        sched = consumer.get("charging_schedule")
        target_source = consumer.get("daily_target_source", "config")
        if sched and sched.get("enabled"):
            if target_source == "historical":
                return bool(consumer.get("path_log"))
            if target_source == "loxone":
                return True
            capacity = float(sched.get("battery_capacity_kwh", 0.0) or 0.0)
            if capacity > 0:
                for day_key in ("weekday", "weekend"):
                    if (sched.get(day_key) or {}).get("daily_rest_soc") is not None:
                        return True
        if target_source in ("historical", "loxone"):
            return True
        return float(consumer.get("daily_target_kwh", 0.0) or 0.0) > 0

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
        end_soc_raw = self._raw_config.get("runtime_settings", {}).get(
            "battery_end_soc_equals_start"
        )
        if end_soc_raw is None:
            self.BATTERY_END_SOC_EQUALS_START = False
        else:
            self.BATTERY_END_SOC_EQUALS_START = bool(end_soc_raw)
        self.THRESHOLD_POWER = self._validate_threshold_power(
            self._get_strict(self._raw_config, ["runtime_settings", "threshold_power"])
        )

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
            'THRESHOLD_POWER': self.get('THRESHOLD_POWER', cast=float),
        }

    def get_battery_params(self) -> dict:
        return {
            'battery_capacity_kwh': self.get('BATTERY_CAPACITY_KWH', cast=float),
            'min_soc': self.get('BATTERY_MIN_SOC', cast=float),
            'max_soc': self.get('BATTERY_MAX_SOC', cast=float),
            'max_power_kw': self.get('BATTERY_MAX_POWER_KW', cast=float),
            'efficiency': self.get('BATTERY_EFFICIENCY', cast=float),
            'end_soc_equals_start': bool(self.get('BATTERY_END_SOC_EQUALS_START', default=False)),
        }

    def get_flexible_consumers(self, optimizer_only: bool = False) -> list:
        """Lädt alle konfigurierten flexiblen Verbraucher."""
        consumers = [
            self._normalize_consumer(raw)
            for raw in self._raw_config.get("flexible_consumers", [])
        ]
        if optimizer_only:
            return [
                c for c in consumers
                if c["optimizer_enabled"]
                and c["nominal_power_kw"] > 0
                and self._consumer_has_daily_target(c)
            ]
        return consumers

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

    def get_threshold_power(self) -> float:
        """Relativer Leistungsschwellenwert (Anteil von battery_max_power_kw)."""
        return self.get('THRESHOLD_POWER', cast=float)

    def get_global_timeout(self, default: int = 5) -> int:
        return self.get('GLOBAL_TIMEOUT', default=default, cast=int)

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

    def get_scenarios(self) -> list[dict]:
        """Lädt alle Backtesting-Szenarien aus dem scenarios-Array in config.json."""
        raw = self._raw_config.get("scenarios")
        if isinstance(raw, list) and raw:
            return [self._normalize_scenario(entry, index) for index, entry in enumerate(raw)]

        legacy = {
            key: value
            for key, value in self._raw_config.items()
            if key.startswith("scenario_settings") and isinstance(value, dict)
        }
        return [
            {
                "id": key,
                "label": key.replace("_", " "),
                "settings": dict(value),
            }
            for key, value in sorted(legacy.items())
        ]

    @staticmethod
    def _normalize_scenario(raw: dict, index: int) -> dict:
        if not isinstance(raw, dict):
            raise ValueError(
                f"Kritischer Konfigurationsfehler: scenarios[{index}] muss ein Objekt sein."
            )

        scenario_id = str(raw.get("id") or f"scenario_{index + 1}").strip()
        if not scenario_id:
            scenario_id = f"scenario_{index + 1}"
        if scenario_id == "runtime_settings":
            raise ValueError(
                "Kritischer Konfigurationsfehler: Die Szenario-ID 'runtime_settings' "
                "ist reserviert (Baseline)."
            )

        settings = raw.get("settings")
        if not isinstance(settings, dict):
            raise KeyError(
                f"Kritischer Konfigurationsfehler: scenarios[{index}] ('{scenario_id}') "
                "benötigt ein 'settings'-Objekt."
            )

        label = str(raw.get("label") or scenario_id).strip() or scenario_id
        return {
            "id": scenario_id,
            "label": label,
            "settings": dict(settings),
        }

    def get_scenario_labels(self) -> dict[str, str]:
        """Anzeigenamen für Backtesting-Szenarien (runtime_settings = Baseline)."""
        labels = {"runtime_settings": "Runtime (Baseline)"}
        for scenario in self.get_scenarios():
            labels[scenario["id"]] = scenario["label"]
        return labels

    def get_backtesting_scenarios(self) -> dict[str, dict]:
        """runtime_settings als Baseline, gefolgt von allen konfigurierten Szenarien."""
        scenarios = {"runtime_settings": dict(self._raw_config["runtime_settings"])}
        for scenario in self.get_scenarios():
            scenarios[scenario["id"]] = scenario["settings"]
        return scenarios

    def get_value(self, name: str, default=None, cast=None):
        return self.get(name, default=default, cast=cast)

    def reload(self) -> None:
        self._load_all()

    def update_runtime_settings(self, new_settings: dict) -> None:
        data = self._read_json_dict(self.config_path)

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

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.write("\n")

        self._raw_config = data
        self._load_dynamic_params()


CONFIG = Config()


def reinit_config() -> None:
    """Lädt die Konfiguration neu (z. B. nach Bootstrap mit neu angelegter config.json)."""
    global CONFIG, CONFIG_JSON_PATH
    CONFIG_JSON_PATH = resolve_config_json_path()
    CONFIG = Config(config_path=CONFIG_JSON_PATH)


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


def get_push_price_cent() -> float:
    return CONFIG.get_push_price_cent()


def get_threshold_power() -> float:
    return CONFIG.get_threshold_power()


def get_global_timeout(default: int = 5) -> int:
    return CONFIG.get_global_timeout(default=default)


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


def get_value(name: str, default=None, cast=None):
    return CONFIG.get_value(name, default=default, cast=cast)


def reload_config() -> None:
    """Lädt config.json neu (z. B. vor jedem main.py-Durchlauf oder in der App)."""
    CONFIG.reload()


def update_runtime_settings(new_settings: dict) -> None:
    return CONFIG.update_runtime_settings(new_settings)