"""System- und UI-Einstellungen aus config.json / local_settings."""
from __future__ import annotations

import os

from settings.json_io import read_json_dict

_SILENT_MODE_KEYS = ("silent_mode", "loxone_silent_mode")


def _validate_silent_mode_bool(raw: object, source: str) -> bool:
    if not isinstance(raw, bool):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: silent_mode in '{source}' "
            "muss true oder false sein."
        )
    return raw


def _read_silent_mode_from_mapping(mapping: dict, source: str) -> bool | None:
    for key in _SILENT_MODE_KEYS:
        if key in mapping:
            return _validate_silent_mode_bool(mapping.get(key), f"{source} ({key})")
    return None


def load_silent_mode(raw_config: dict, local_settings: dict, local_settings_path: str) -> bool:
    local_val = _read_silent_mode_from_mapping(local_settings, local_settings_path)
    if local_val is not None:
        return local_val
    system = raw_config.get("system")
    if not isinstance(system, dict):
        return True
    for key in _SILENT_MODE_KEYS:
        if key in system:
            return _validate_silent_mode_bool(
                system.get(key),
                f"config.json (system.{key})",
            )
    return True


def load_loxone_silent_mode(raw_config: dict, local_settings: dict, local_settings_path: str) -> bool:
    """Deprecated alias for :func:`load_silent_mode`."""
    return load_silent_mode(raw_config, local_settings, local_settings_path)


def load_local_settings_document(local_settings_path: str) -> dict:
    path = local_settings_path
    if not os.path.isfile(path):
        return {}
    return read_json_dict(path)


def load_ehal_loxone_http_port(raw_config: dict) -> int:
    """Daemon port for Earnie_Request_Optimize / alive (default 8541)."""
    raw = raw_config.get("system", {}).get("ehal_loxone_http_port")
    if raw is None:
        return 8541
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Kritischer Konfigurationsfehler: system.ehal_loxone_http_port "
            "muss eine ganze Zahl sein."
        ) from exc
    if not 1024 <= value <= 65535:
        raise ValueError(
            "Kritischer Konfigurationsfehler: system.ehal_loxone_http_port "
            "muss zwischen 1024 und 65535 liegen."
        )
    return value


def load_ui_fragment_refresh_sec(raw_config: dict, key: str, default: int) -> int:
    raw = raw_config.get("ui", {}).get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: ui.{key} muss eine ganze Zahl sein."
        ) from exc
    if value < 1:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: ui.{key} muss mindestens 1 sein."
        )
    return value


def _validate_ui_bool(raw: object, source: str) -> bool:
    if not isinstance(raw, bool):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: {source} muss true oder false sein."
        )
    return raw


def load_ui_bool(raw_config: dict, key: str, default: bool) -> bool:
    raw = raw_config.get("ui", {}).get(key)
    if raw is None:
        return default
    return _validate_ui_bool(raw, f"ui.{key}")


def load_ui_chart_debug_capture_enabled(
    raw_config: dict,
    local_settings: dict,
    local_settings_path: str,
) -> bool:
    """Chart-Debug-ZIP: local_settings.json überschreibt ui.chart_debug_capture_enabled."""
    if "chart_debug_capture_enabled" in local_settings:
        return _validate_ui_bool(
            local_settings.get("chart_debug_capture_enabled"),
            f"{local_settings_path} (chart_debug_capture_enabled)",
        )
    return load_ui_bool(raw_config, "chart_debug_capture_enabled", False)


def load_ui_streamlit_port(raw_config: dict) -> int:
    raw = raw_config.get("ui", {}).get("streamlit_port")
    if raw is None:
        return 8501
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Kritischer Konfigurationsfehler: ui.streamlit_port muss eine ganze Zahl sein."
        ) from exc
    if not 1024 <= value <= 65535:
        raise ValueError(
            "Kritischer Konfigurationsfehler: ui.streamlit_port muss zwischen 1024 und 65535 liegen."
        )
    return value


def load_ui_chart_debug_capture_dir(raw_config: dict) -> str:
    raw = raw_config.get("ui", {}).get("chart_debug_capture_dir")
    if raw is None:
        return "chart_debug"
    path = str(raw).strip()
    if not path:
        raise ValueError(
            "Kritischer Konfigurationsfehler: ui.chart_debug_capture_dir darf nicht leer sein."
        )
    return path
