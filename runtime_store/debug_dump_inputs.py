"""Gemeinsame Repro-Inputs fuer Debug-Dumps und Prod-Archive."""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

from runtime_store.persist_paths import (
    resolve_config_json_path,
    resolve_deviation_rules_json_path,
    resolve_local_settings_json_path,
    resolve_runtime_prefixed_path,
    runtime_dir,
)

_ENV_KEYS = (
    "ENERGY_OPTIMIZER_CONFIG_PATH",
    "ENERGY_OPTIMIZER_DEVIATION_RULES_PATH",
    "ENERGY_OPTIMIZER_LOCAL_SETTINGS_PATH",
    "ENERGY_OPTIMIZER_RUNTIME_DIR",
)


def collect_dump_context() -> dict[str, object]:
    """Liefert aufgeloeste Pfade und relevante Env-Overrides fuer Repro-Dumps."""
    env_overrides = {
        key: value for key in _ENV_KEYS if (value := os.environ.get(key, "").strip())
    }
    extra_paths = _resolve_optional_input_paths()
    return {
        "env_overrides": env_overrides,
        "resolved_paths": {
            "config_json": resolve_config_json_path(),
            "deviation_rules_json": resolve_deviation_rules_json_path(),
            "local_settings_json": resolve_local_settings_json_path(),
            "runtime_dir": runtime_dir(),
            **extra_paths,
        },
    }


def iter_input_files() -> list[tuple[str, str]]:
    """Dateien, die fuer spaeteres Reproduzieren mit archiviert werden sollten."""
    context = collect_dump_context()
    resolved = context["resolved_paths"]
    candidates = (
        ("inputs/config.json", resolved["config_json"]),
        ("inputs/deviation_rules.json", resolved["deviation_rules_json"]),
        ("inputs/local_settings.json", resolved["local_settings_json"]),
        ("inputs/price_model_coefficients.json", resolved.get("forecast_model_path")),
        ("inputs/cons_data_hourly.csv", resolved.get("cons_data_path")),
    )
    files: list[tuple[str, str]] = []
    for archive_name, source_path in candidates:
        if isinstance(source_path, str) and os.path.isfile(source_path):
            files.append((source_path, archive_name))
    return files


def write_inputs_to_zip(archive: zipfile.ZipFile) -> list[str]:
    """Schreibt vorhandene Repro-Inputs in ein ZIP und liefert deren Arcnames."""
    written: list[str] = []
    for source_path, archive_name in iter_input_files():
        archive.write(source_path, arcname=archive_name)
        written.append(archive_name)
    return written


def copy_inputs_to_directory(target_dir: str | Path) -> list[str]:
    """Kopiert vorhandene Repro-Inputs in ein Zielverzeichnis."""
    target_root = Path(target_dir)
    copied: list[str] = []
    for source_path, archive_name in iter_input_files():
        target_path = target_root / archive_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied.append(archive_name.replace("\\", "/"))
    return copied


def _resolve_optional_input_paths() -> dict[str, str]:
    config_path = resolve_config_json_path()
    config_doc = _read_json_dict(config_path)
    return {
        "forecast_model_path": _resolve_forecast_model_path(config_doc),
        "cons_data_path": _resolve_cons_data_path(config_doc),
    }


def _read_json_dict(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _resolve_forecast_model_path(config_doc: dict) -> str:
    block = config_doc.get("market_prices")
    if not isinstance(block, dict):
        return os.path.abspath("data/cache/price_model_coefficients.json")
    configured = str(block.get("forecast_model_path") or "").strip()
    if not configured:
        return os.path.abspath("data/cache/price_model_coefficients.json")
    return os.path.abspath(resolve_runtime_prefixed_path(configured))


def _resolve_cons_data_path(config_doc: dict) -> str:
    block = config_doc.get("file_paths_battery_simulation")
    if not isinstance(block, dict):
        return ""
    configured = str(block.get("path_cons_data") or "").strip()
    if not configured:
        return ""
    return os.path.abspath(resolve_runtime_prefixed_path(configured))
