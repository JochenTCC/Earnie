"""
persist_paths.py – Pfade für persistente Laufzeitdateien (unter runtime/).
"""
from __future__ import annotations

import os

from runtime_store.env_vars import read_env, read_env_or

_DEFAULT_RUNTIME_DIR = "runtime"
_DEFAULT_DOTENV = os.path.join("config", ".env")
_LEGACY_DOTENV = ".env"


def runtime_dir() -> str:
    return read_env_or("RUNTIME_DIR", _DEFAULT_RUNTIME_DIR)


def runtime_path(filename: str) -> str:
    return os.path.join(runtime_dir(), filename)


def resolve_backtesting_log_dir() -> str:
    """Zielordner für backtesting_log.json und backtesting_hourly.csv (UI und Laufzeit)."""
    return runtime_dir()


def resolve_runtime_prefixed_path(configured_path: str) -> str:
    """
    Relative Pfade mit ``runtime/``-Präfix gegen ``runtime_dir()`` auflösen.

    So greift ``EARNIE_RUNTIME_DIR`` (bzw. Legacy ``ENERGY_OPTIMIZER_RUNTIME_DIR``) auch für ``path_cons_data`` in
    config.json (z. B. Dev mit NAS-Config, Docker unverändert).
    """
    if os.path.isabs(configured_path):
        return configured_path
    norm = configured_path.replace("\\", "/")
    if norm.startswith("runtime/"):
        return runtime_path(norm[len("runtime/") :])
    return configured_path


def consumer_state_file() -> str:
    return runtime_path("flexible_consumers_state.json")


def pv_counter_state_file() -> str:
    return runtime_path("pv_counter_state.json")


def cons_data_pending_file() -> str:
    return runtime_path("cons_data_pending.json")


def log_file() -> str:
    return runtime_path("earnie.log")


def consumption_profiles_file() -> str:
    return runtime_path("consumption_profiles.csv")


def total_consumption_profiles_file() -> str:
    return runtime_path("total_consumption_profiles.csv")


def flexible_consumer_profiles_file() -> str:
    return runtime_path("flexible_consumer_profiles.csv")


def legacy_history_csv_file() -> str:
    return runtime_path("system_history_log.csv")


def default_cons_data_file() -> str:
    return runtime_path("cons_data_hourly.csv")


def bundled_config_dir() -> str:
    """Im Image gebündelte Config-Vorlagen (nicht vom NAS-Volume überschrieben)."""
    return os.path.join("share", "config")


def bundled_config_example_file() -> str:
    return os.path.join(bundled_config_dir(), "config.example.json")


def bundled_config_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "config.minimal.json")


def bundled_config_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "config.schema.json")


def resolve_config_template_path() -> str:
    """Vorlage für config.example.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = os.path.join("config", "config.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_config_minimal_template_path() -> str:
    """Vorlage für neue config.json (Greenfield-Bootstrap, ohne Hausdaten)."""
    preferred = os.path.join("config", "config.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_config_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def config_example_file() -> str:
    """Pfad zur Config-Vorlage im Persistenz-Ordner (für Drift-Vergleich)."""
    preferred = os.path.join("config", "config.example.json")
    legacy = "config.example.json"
    if os.path.isfile(preferred):
        return preferred
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def config_schema_file() -> str:
    """Pfad zum JSON-Schema im Persistenz-Ordner."""
    preferred = os.path.join("config", "config.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_config_schema_template_path() -> str:
    """Schema-Vorlage: Mount, Legacy oder gebündelte Image-Kopie."""
    return config_schema_file()


def resolve_config_json_path() -> str:
    """Konfigurationspfad: ENV > config/config.json > Legacy config.json im Repo-Wurzelverzeichnis."""
    env = read_env("CONFIG_PATH")
    if env:
        return env
    preferred = os.path.join("config", "config.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.json"
    if os.path.isfile(legacy):
        return legacy
    return preferred


def _config_directory_from_env() -> str | None:
    """Verzeichnis der per ENV gesetzten config.json, sonst None."""
    env = read_env("CONFIG_PATH")
    if not env:
        return None
    return os.path.dirname(os.path.abspath(env))


def _resolve_sidecar_json_path(
    *,
    env_suffix: str,
    filename: str,
    default_path: str,
    legacy_basename: str | None = None,
) -> str:
    """
    Sidecar-JSON neben config.json, wenn CONFIG_PATH per ENV gesetzt ist.

    Reihenfolge: explizite Sidecar-ENV > Datei im Config-Verzeichnis > Default > Legacy.
    """
    env = read_env(env_suffix)
    if env:
        return env
    config_dir = _config_directory_from_env()
    if config_dir:
        co_located = os.path.join(config_dir, filename)
        if os.path.isfile(co_located):
            return co_located
    if os.path.isfile(default_path):
        return default_path
    if legacy_basename and os.path.isfile(legacy_basename):
        return legacy_basename
    return default_path


def local_settings_file() -> str:
    return runtime_path("local_settings.json")


def local_settings_example_file() -> str:
    return runtime_path("local_settings.example.json")


def resolve_local_settings_template_path() -> str:
    """Vorlage für local_settings.json: Runtime-Mount oder gebündelte Image-Kopie."""
    preferred = local_settings_example_file()
    if os.path.isfile(preferred):
        return preferred
    bundled = os.path.join(bundled_config_dir(), "local_settings.example.json")
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_local_settings_json_path() -> str:
    """Maschinenspezifische Einstellungen: ENV > runtime/local_settings.json."""
    env = read_env("LOCAL_SETTINGS_PATH")
    if env:
        return env
    return local_settings_file()


def bundled_backtesting_scenarios_example_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.example.json")


def bundled_backtesting_scenarios_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.minimal.json")


def bundled_backtesting_scenarios_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.schema.json")


def resolve_backtesting_scenarios_template_path() -> str:
    """Vorlage für backtesting_scenarios.example.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = os.path.join("config", "backtesting_scenarios.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "backtesting_scenarios.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_backtesting_scenarios_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_minimal_template_path() -> str:
    """Vorlage für neue backtesting_scenarios.json (leere Szenarien)."""
    preferred = os.path.join("config", "backtesting_scenarios.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_backtesting_scenarios_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_schema_template_path() -> str:
    """Schema-Vorlage für backtesting_scenarios.json."""
    preferred = os.path.join("config", "backtesting_scenarios.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "backtesting_scenarios.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_backtesting_scenarios_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_json_path() -> str:
    """Pfad zu backtesting_scenarios.json: ENV > neben config.json > config/ > Legacy."""
    return _resolve_sidecar_json_path(
        env_suffix="BACKTESTING_SCENARIOS_PATH",
        filename="backtesting_scenarios.json",
        default_path=os.path.join("config", "backtesting_scenarios.json"),
        legacy_basename="backtesting_scenarios.json",
    )


def bundled_tariffs_example_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.example.json")


def bundled_tariffs_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.minimal.json")


def bundled_tariffs_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.schema.json")


def resolve_tariffs_template_path() -> str:
    preferred = os.path.join("config", "tariffs.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_minimal_template_path() -> str:
    """Vorlage für neue tariffs.json (leere Tarif-Kataloge)."""
    preferred = os.path.join("config", "tariffs.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_schema_template_path() -> str:
    preferred = os.path.join("config", "tariffs.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_json_path() -> str:
    """Pfad zu tariffs.json: ENV > neben config.json > config/."""
    return _resolve_sidecar_json_path(
        env_suffix="TARIFFS_PATH",
        filename="tariffs.json",
        default_path=os.path.join("config", "tariffs.json"),
    )


def bundled_house_profiles_example_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.example.json")


def bundled_house_profiles_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.minimal.json")


def bundled_house_profiles_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.schema.json")


def resolve_house_profiles_template_path() -> str:
    preferred = os.path.join("config", "house_profiles.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_minimal_template_path() -> str:
    """Vorlage für neue house_profiles.json (leere Profile)."""
    preferred = os.path.join("config", "house_profiles.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_schema_template_path() -> str:
    preferred = os.path.join("config", "house_profiles.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_json_path() -> str:
    """Pfad zu house_profiles.json: ENV > neben config.json > config/."""
    return _resolve_sidecar_json_path(
        env_suffix="HOUSE_PROFILES_PATH",
        filename="house_profiles.json",
        default_path=os.path.join("config", "house_profiles.json"),
    )


def bundled_components_example_file() -> str:
    return os.path.join(bundled_config_dir(), "components.example.json")


def bundled_components_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "components.minimal.json")


def bundled_components_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "components.schema.json")


def resolve_components_template_path() -> str:
    preferred = os.path.join("config", "components.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_minimal_template_path() -> str:
    """Vorlage für neue components.json (leere Kataloge)."""
    preferred = os.path.join("config", "components.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_schema_template_path() -> str:
    preferred = os.path.join("config", "components.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_json_path() -> str:
    """Pfad zu components.json: ENV > neben config.json > config/."""
    return _resolve_sidecar_json_path(
        env_suffix="COMPONENTS_PATH",
        filename="components.json",
        default_path=os.path.join("config", "components.json"),
    )


def bundled_deviation_rules_example_file() -> str:
    return os.path.join(bundled_config_dir(), "deviation_rules.example.json")


def bundled_deviation_rules_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "deviation_rules.schema.json")


def resolve_deviation_rules_template_path() -> str:
    """Vorlage für deviation_rules.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = os.path.join("config", "deviation_rules.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_deviation_rules_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_deviation_rules_schema_template_path() -> str:
    """Schema-Vorlage für deviation_rules.json."""
    preferred = os.path.join("config", "deviation_rules.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_deviation_rules_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_deviation_rules_json_path() -> str:
    """Pfad zu deviation_rules.json: ENV > config/ > Fallback auf Vorlage."""
    env = read_env("DEVIATION_RULES_PATH")
    if env:
        return env
    preferred = os.path.join("config", "deviation_rules.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.json"
    if os.path.isfile(legacy):
        return legacy
    return resolve_deviation_rules_template_path()


def bundled_dotenv_example_file() -> str:
    return os.path.join(bundled_config_dir(), ".env.example")


def resolve_dotenv_path() -> str:
    """Pfad zur .env: ENV > config/.env > Legacy ./.env im Repo-Wurzelverzeichnis."""
    env = read_env("DOTENV_PATH")
    if env:
        return env
    if os.path.isfile(_DEFAULT_DOTENV):
        return _DEFAULT_DOTENV
    if os.path.isfile(_LEGACY_DOTENV):
        return _LEGACY_DOTENV
    return _DEFAULT_DOTENV


def resolve_dotenv_template_path() -> str:
    """Vorlage für .env: Repo-.env.example oder gebündelte Image-Kopie."""
    if os.path.isfile(".env.example"):
        return ".env.example"
    bundled = bundled_dotenv_example_file()
    if os.path.isfile(bundled):
        return bundled
    return bundled
