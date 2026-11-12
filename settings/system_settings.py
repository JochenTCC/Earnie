"""System- und UI-Einstellungen aus config.json / local_settings."""
from __future__ import annotations

import json
import logging
import os

from settings.json_io import read_json_dict

logger = logging.getLogger(__name__)

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


def write_silent_mode_to_local_settings(local_settings_path: str, silent: bool) -> None:
    """Merge ``silent_mode`` into local_settings.json; drop legacy key. Preserve other keys."""
    if not isinstance(silent, bool):
        raise ValueError("silent_mode muss true oder false sein.")
    path = local_settings_path
    document = load_local_settings_document(path)
    document["silent_mode"] = silent
    document.pop("loxone_silent_mode", None)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_ehal_http_port(raw_config: dict) -> int:
    """Daemon port for Request Optimize / telemetry / status.json (default 8541).

    Prefers ``system.ehal_http_port``; falls back to legacy
    ``system.ehal_loxone_http_port`` (Binding Lx3).
    """
    system = raw_config.get("system") if isinstance(raw_config.get("system"), dict) else {}
    raw = system.get("ehal_http_port")
    if raw is None:
        raw = system.get("ehal_loxone_http_port")
    if raw is None:
        return 8541
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Kritischer Konfigurationsfehler: system.ehal_http_port "
            "muss eine ganze Zahl sein."
        ) from exc
    if not 1024 <= value <= 65535:
        raise ValueError(
            "Kritischer Konfigurationsfehler: system.ehal_http_port "
            "muss zwischen 1024 und 65535 liegen."
        )
    return value


def load_ehal_loxone_http_port(raw_config: dict) -> int:
    """Deprecated alias for :func:`load_ehal_http_port`."""
    return load_ehal_http_port(raw_config)


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


_REMOVED_DEBUG_DUMP_KEY = "chart_debug_capture_enabled"
_REMOVED_DEBUG_DUMP_ENV = "EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED"
_warned_removed_debug_dump_sources: set[str] = set()


def _warn_once(source: str, message: str, *args: object) -> None:
    """Config is reloaded on every UI rerun; one warning per process is enough."""
    if source in _warned_removed_debug_dump_sources:
        return
    _warned_removed_debug_dump_sources.add(source)
    logger.warning(message, *args)


def reject_removed_debug_dump_flag(
    raw_config: dict,
    local_settings: dict,
    local_settings_path: str,
) -> None:
    """The Debug-Dump switch is gone; the support package is always available.

    ``config.json`` is a pack file: a leftover key means the migration
    ``dm6.debug_dump_flag_removal`` did not run, so fail loud. ``local_settings.json``
    and the env var are machine-local and never block the daemon; they only warn.
    """
    ui = raw_config.get("ui")
    if isinstance(ui, dict) and _REMOVED_DEBUG_DUMP_KEY in ui:
        raise ValueError(
            "Kritischer Konfigurationsfehler: ui.chart_debug_capture_enabled wurde "
            "entfernt (Support-Paket ist immer verfügbar). Bitte die Konfig-Migration "
            "ausführen (Assistent in der App oder python -m scripts.migrate_config)."
        )
    if _REMOVED_DEBUG_DUMP_KEY in local_settings:
        _warn_once(
            local_settings_path,
            "%s: chart_debug_capture_enabled wird nicht mehr ausgewertet "
            "(Support-Paket ist immer verfügbar) – Eintrag bitte löschen.",
            local_settings_path,
        )
    if os.environ.get(_REMOVED_DEBUG_DUMP_ENV, "").strip():
        _warn_once(
            _REMOVED_DEBUG_DUMP_ENV,
            "%s wird nicht mehr ausgewertet (Support-Paket ist immer verfügbar) – "
            "Variable bitte entfernen.",
            _REMOVED_DEBUG_DUMP_ENV,
        )


def load_shadow_feed_enabled(
    local_settings: dict,
    local_settings_path: str,
) -> bool:
    """Prod shadow feed recorder (local_settings only; default off)."""
    if "shadow_feed_enabled" not in local_settings:
        return False
    return _validate_ui_bool(
        local_settings.get("shadow_feed_enabled"),
        f"{local_settings_path} (shadow_feed_enabled)",
    )


def load_shadow_feed_retention_days(
    local_settings: dict,
    local_settings_path: str,
) -> int:
    """JSONL retention days for shadow_feed (default 14)."""
    if "shadow_feed_retention_days" not in local_settings:
        return 14
    raw = local_settings.get("shadow_feed_retention_days")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: {local_settings_path} "
            "(shadow_feed_retention_days) muss eine ganze Zahl sein."
        ) from exc
    if value < 1:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: {local_settings_path} "
            "(shadow_feed_retention_days) muss mindestens 1 sein."
        )
    return value


def load_recorder_enabled(
    local_settings: dict,
    local_settings_path: str,
) -> bool:
    """Cycle recorder (Regression R-Rec); default on."""
    if "recorder_enabled" not in local_settings:
        return True
    return _validate_ui_bool(
        local_settings.get("recorder_enabled"),
        f"{local_settings_path} (recorder_enabled)",
    )


def load_recorder_retention_days(
    local_settings: dict,
    local_settings_path: str,
) -> int:
    """Ring-buffer retention days for cycle recorder (default 7)."""
    if "recorder_retention_days" not in local_settings:
        return 7
    raw = local_settings.get("recorder_retention_days")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: {local_settings_path} "
            "(recorder_retention_days) muss eine ganze Zahl sein."
        ) from exc
    if value < 1:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: {local_settings_path} "
            "(recorder_retention_days) muss mindestens 1 sein."
        )
    return value


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
