"""
config_drift.py – Vergleich der Anwender-config.json mit config.example.json (nur Hinweise, kein Auto-Merge).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from .persist_paths import config_example_file, resolve_config_json_path

_SKIP_KEYS = frozenset({"$schema"})
_FLEXIBLE_CONSUMERS_KEY = "flexible_consumers"


@dataclass(frozen=True)
class ConfigDriftItem:
    path: str
    example_value: Any


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} muss ein JSON-Objekt sein.")
    return data


def _format_example_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > 120:
            return text[:117] + "..."
        return text
    return repr(value)


def _find_missing_in_object(
    example: dict[str, Any],
    actual: dict[str, Any],
    prefix: str,
) -> list[ConfigDriftItem]:
    missing: list[ConfigDriftItem] = []
    for key, example_value in example.items():
        if key in _SKIP_KEYS:
            continue
        path = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            missing.append(ConfigDriftItem(path=path, example_value=example_value))
            continue
        actual_value = actual[key]
        if key == _FLEXIBLE_CONSUMERS_KEY:
            missing.extend(_find_missing_flexible_consumers(example_value, actual_value))
            continue
        if isinstance(example_value, dict) and isinstance(actual_value, dict):
            missing.extend(_find_missing_in_object(example_value, actual_value, path))
    return missing


def _find_missing_flexible_consumers(
    example_list: Any,
    actual_list: Any,
) -> list[ConfigDriftItem]:
    if not isinstance(example_list, list):
        return []
    actual_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(actual_list, list):
        for item in actual_list:
            if isinstance(item, dict) and item.get("id"):
                actual_by_id[str(item["id"])] = item

    missing: list[ConfigDriftItem] = []
    for example_item in example_list:
        if not isinstance(example_item, dict) or not example_item.get("id"):
            continue
        consumer_id = str(example_item["id"])
        prefix = f"{_FLEXIBLE_CONSUMERS_KEY}[id={consumer_id}]"
        actual_item = actual_by_id.get(consumer_id)
        if actual_item is None:
            missing.append(
                ConfigDriftItem(path=prefix, example_value=example_item)
            )
            continue
        missing.extend(_find_missing_in_object(example_item, actual_item, prefix))
    return missing


def find_config_drift(
    example: dict[str, Any],
    actual: dict[str, Any],
) -> list[ConfigDriftItem]:
    return _find_missing_in_object(example, actual, prefix="")


def load_config_drift_items(
    *,
    template_path: str | None = None,
    config_path: str | None = None,
) -> list[ConfigDriftItem]:
    template = template_path or config_example_file()
    config_file = config_path or resolve_config_json_path()
    if not os.path.isfile(template):
        raise FileNotFoundError(
            f"Config-Vorlage '{template}' nicht gefunden – Drift-Prüfung nicht möglich."
        )
    if not os.path.isfile(config_file):
        raise FileNotFoundError(
            f"Konfigurationsdatei '{config_file}' nicht gefunden – Drift-Prüfung nicht möglich."
        )
    example = _load_json(template)
    actual = _load_json(config_file)
    return find_config_drift(example, actual)


def log_config_drift(
    logger: logging.Logger,
    *,
    template_path: str | None = None,
    config_path: str | None = None,
) -> list[ConfigDriftItem]:
    try:
        items = load_config_drift_items(
            template_path=template_path,
            config_path=config_path,
        )
    except FileNotFoundError as exc:
        logger.warning("config_drift: %s", exc)
        return []
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("config_drift: Prüfung fehlgeschlagen: %s", exc)
        return []

    if not items:
        return []

    logger.warning(
        "config: %s neue Einträge in %s – bitte manuell in %s ergänzen:",
        len(items),
        template_path or config_example_file(),
        config_path or resolve_config_json_path(),
    )
    for item in items:
        logger.warning(
            "  - %s  (Beispiel: %s)",
            item.path,
            _format_example_value(item.example_value),
        )
    return items


def format_drift_message(items: list[ConfigDriftItem]) -> str:
    lines = [
        f"**{len(items)} neue Config-Einträge** in `config.example.json` – bitte manuell in "
        f"`{resolve_config_json_path()}` ergänzen (kein automatisches Überschreiben):"
    ]
    for item in items:
        lines.append(
            f"- `{item.path}` → Beispiel: `{_format_example_value(item.example_value)}`"
        )
    return "\n\n".join(lines)
