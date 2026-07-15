"""System-, UI- und Event-Trigger-Einstellungen aus config.json / local_settings."""
from __future__ import annotations

import os

from settings.json_io import read_json_dict


def _validate_loxone_silent_mode_bool(raw: object, source: str) -> bool:
    if not isinstance(raw, bool):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: loxone_silent_mode in '{source}' "
            "muss true oder false sein."
        )
    return raw


def load_loxone_silent_mode(raw_config: dict, local_settings: dict, local_settings_path: str) -> bool:
    if "loxone_silent_mode" in local_settings:
        return _validate_loxone_silent_mode_bool(
            local_settings.get("loxone_silent_mode"),
            local_settings_path,
        )
    system = raw_config.get("system")
    if not isinstance(system, dict):
        return False
    raw = system.get("loxone_silent_mode")
    if raw is None:
        return True
    return _validate_loxone_silent_mode_bool(raw, "config.json (system.loxone_silent_mode)")


def load_local_settings_document(local_settings_path: str) -> dict:
    path = local_settings_path
    if not os.path.isfile(path):
        return {}
    return read_json_dict(path)


def load_event_trigger_enabled(raw_config: dict) -> bool:
    raw = raw_config.get("system", {}).get("event_trigger_enabled")
    if raw is None:
        return True
    if not isinstance(raw, bool):
        raise ValueError(
            "Kritischer Konfigurationsfehler: system.event_trigger_enabled "
            "muss true oder false sein."
        )
    return raw


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


def load_event_poll_interval_sec(raw_config: dict) -> int:
    system = raw_config.get("system", {})
    raw = system.get("event_poll_interval_sec")
    if raw is None:
        raw = system.get("charging_poll_interval_sec")
    if raw is None:
        return 60
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Kritischer Konfigurationsfehler: system.event_poll_interval_sec "
            "muss eine ganze Zahl sein."
        ) from exc
    if value < 1:
        raise ValueError(
            "Kritischer Konfigurationsfehler: system.event_poll_interval_sec "
            "muss mindestens 1 sein."
        )
    return value


def normalize_event_trigger(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"system.event_triggers[{index}] muss ein Objekt sein.")
    trigger_id = str(raw.get("id", "")).strip()
    if not trigger_id:
        raise ValueError(f"system.event_triggers[{index}]: id fehlt.")
    loxone_name = str(raw.get("loxone_name", "")).strip()
    if not loxone_name:
        raise ValueError(
            f"system.event_triggers[{index}] ('{trigger_id}'): loxone_name fehlt."
        )
    signal_type = str(raw.get("signal_type", "")).strip().lower()
    if signal_type not in ("binary", "text", "analog"):
        raise ValueError(
            f"system.event_triggers[{index}] ('{trigger_id}'): "
            "signal_type muss 'binary', 'text' oder 'analog' sein."
        )
    on_change = str(raw.get("on_change", "")).strip().lower()
    if signal_type == "binary":
        allowed = {"any", "rising", "falling"}
    else:
        allowed = {"any"}
    if on_change not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(
            f"system.event_triggers[{index}] ('{trigger_id}'): "
            f"on_change muss einer von [{allowed_text}] sein."
        )
    label = str(raw.get("label", trigger_id)).strip() or trigger_id
    return {
        "id": trigger_id,
        "loxone_name": loxone_name,
        "signal_type": signal_type,
        "on_change": on_change,
        "label": label,
    }


def load_event_triggers(raw_config: dict) -> list[dict]:
    raw = raw_config.get("system", {}).get("event_triggers")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Kritischer Konfigurationsfehler: system.event_triggers muss ein Array sein.")
    seen: set[str] = set()
    triggers: list[dict] = []
    for index, item in enumerate(raw):
        spec = normalize_event_trigger(item, index)
        if spec["id"] in seen:
            raise ValueError(
                f"Kritischer Konfigurationsfehler: system.event_triggers enthält "
                f"doppelte id '{spec['id']}'."
            )
        seen.add(spec["id"])
        triggers.append(spec)
    return triggers
