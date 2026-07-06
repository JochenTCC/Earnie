"""
persist_paths.py – Pfade für persistente Laufzeitdateien (unter runtime/).
"""
from __future__ import annotations

import os

_RUNTIME_DIR_ENV = "ENERGY_OPTIMIZER_RUNTIME_DIR"
_DEFAULT_RUNTIME_DIR = "runtime"
_LOCAL_SETTINGS_ENV = "ENERGY_OPTIMIZER_LOCAL_SETTINGS_PATH"


def runtime_dir() -> str:
    return os.environ.get(_RUNTIME_DIR_ENV, _DEFAULT_RUNTIME_DIR)


def runtime_path(filename: str) -> str:
    return os.path.join(runtime_dir(), filename)


def resolve_runtime_prefixed_path(configured_path: str) -> str:
    """
    Relative Pfade mit ``runtime/``-Präfix gegen ``runtime_dir()`` auflösen.

    So greift ``ENERGY_OPTIMIZER_RUNTIME_DIR`` auch für ``path_cons_data`` in
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
    return runtime_path("energy_optimizer.log")


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


def bundled_config_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "config.schema.json")


def resolve_config_template_path() -> str:
    """Vorlage für config.json: Mount, Legacy oder gebündelte Image-Kopie."""
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
    env = os.environ.get("ENERGY_OPTIMIZER_CONFIG_PATH", "").strip()
    if env:
        return env
    preferred = os.path.join("config", "config.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.json"
    if os.path.isfile(legacy):
        return legacy
    return preferred


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
    env = os.environ.get(_LOCAL_SETTINGS_ENV, "").strip()
    if env:
        return env
    return local_settings_file()


def bundled_backtesting_scenarios_example_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.example.json")


def bundled_backtesting_scenarios_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.schema.json")


def resolve_backtesting_scenarios_template_path() -> str:
    """Vorlage für backtesting_scenarios.json: Mount, Legacy oder gebündelte Image-Kopie."""
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
    """Pfad zu backtesting_scenarios.json: ENV > config/ > Legacy im Repo-Wurzelverzeichnis."""
    env = os.environ.get("ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH", "").strip()
    if env:
        return env
    preferred = os.path.join("config", "backtesting_scenarios.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "backtesting_scenarios.json"
    if os.path.isfile(legacy):
        return legacy
    return preferred


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
    env = os.environ.get("ENERGY_OPTIMIZER_DEVIATION_RULES_PATH", "").strip()
    if env:
        return env
    preferred = os.path.join("config", "deviation_rules.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.json"
    if os.path.isfile(legacy):
        return legacy
    return resolve_deviation_rules_template_path()
