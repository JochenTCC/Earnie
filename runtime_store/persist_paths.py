"""
persist_paths.py – Pfade für persistente Laufzeitdateien (unter runtime/).
"""
from __future__ import annotations

import os

_RUNTIME_DIR_ENV = "ENERGY_OPTIMIZER_RUNTIME_DIR"
_DEFAULT_RUNTIME_DIR = "runtime"


def runtime_dir() -> str:
    return os.environ.get(_RUNTIME_DIR_ENV, _DEFAULT_RUNTIME_DIR)


def runtime_path(filename: str) -> str:
    return os.path.join(runtime_dir(), filename)


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


def config_example_file() -> str:
    return "config.example.json"


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
