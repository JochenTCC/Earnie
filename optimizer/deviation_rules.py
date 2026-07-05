"""Laden und Validierung von config/deviation_rules.json (Epic Soll-Ist)."""
from __future__ import annotations

import json
import os
from typing import Any

from runtime_store.persist_paths import resolve_deviation_rules_json_path

_REQUIRED_ROOT_KEYS = ("version", "tolerances", "categories", "rules", "fallback")
_REQUIRED_CATEGORIES = ("hint", "warning", "error")
_REQUIRED_RULE_KEYS = ("id", "category", "priority", "scope", "when", "message")


def _read_json_dict(path: str) -> dict[str, Any]:
    last_decode_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                data = json.load(handle)
        except UnicodeDecodeError as exc:
            last_decode_error = exc
            continue
        except json.JSONDecodeError:
            raise
        if not isinstance(data, dict):
            raise ValueError(f"Abweichungsregeln '{path}' müssen ein JSON-Objekt sein.")
        return data
    raise ValueError(
        f"Abweichungsregeln '{path}' sind weder UTF-8 noch cp1252 lesbar."
    ) from last_decode_error


def validate_deviation_rules_document(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Prüft Pflichtfelder; wirft ValueError bei ungültiger Struktur."""
    missing = [key for key in _REQUIRED_ROOT_KEYS if key not in data]
    if missing:
        raise ValueError(
            f"Abweichungsregeln '{source}' unvollständig — fehlende Felder: {', '.join(missing)}"
        )
    categories = data["categories"]
    if not isinstance(categories, dict):
        raise ValueError(f"Abweichungsregeln '{source}': categories muss ein Objekt sein.")
    for key in _REQUIRED_CATEGORIES:
        if key not in categories:
            raise ValueError(
                f"Abweichungsregeln '{source}': Kategorie '{key}' fehlt."
            )
    rules = data["rules"]
    if not isinstance(rules, list):
        raise ValueError(f"Abweichungsregeln '{source}': rules muss ein Array sein.")
    seen_ids: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(
                f"Abweichungsregeln '{source}': rules[{index}] muss ein Objekt sein."
            )
        missing_rule = [key for key in _REQUIRED_RULE_KEYS if key not in rule]
        if missing_rule:
            raise ValueError(
                f"Abweichungsregeln '{source}': rules[{index}] fehlt: {', '.join(missing_rule)}"
            )
        rule_id = str(rule["id"])
        if rule_id in seen_ids:
            raise ValueError(
                f"Abweichungsregeln '{source}': doppelte Regel-ID '{rule_id}'."
            )
        seen_ids.add(rule_id)
        if rule["category"] not in _REQUIRED_CATEGORIES:
            raise ValueError(
                f"Abweichungsregeln '{source}': Regel '{rule_id}' hat unbekannte category."
            )
        when = rule["when"]
        if not isinstance(when, list) or not when:
            raise ValueError(
                f"Abweichungsregeln '{source}': Regel '{rule_id}' braucht mindestens ein Prädikat."
            )
    fallback = data["fallback"]
    if fallback.get("on_unclassified_mismatch") not in ("none", "warning", "error"):
        raise ValueError(
            f"Abweichungsregeln '{source}': fallback.on_unclassified_mismatch ungültig."
        )
    tolerances = data["tolerances"]
    if "power_kw" not in tolerances:
        raise ValueError(
            f"Abweichungsregeln '{source}': tolerances.power_kw fehlt."
        )
    return data


def load_deviation_rules(path: str | None = None) -> dict[str, Any]:
    """Lädt und validiert die Regeldatei."""
    resolved = path or resolve_deviation_rules_json_path()
    if not os.path.isfile(resolved):
        raise FileNotFoundError(
            f"Abweichungsregeln nicht gefunden: '{resolved}'. "
            "Kopiere config/deviation_rules.example.json nach config/deviation_rules.json."
        )
    try:
        data = _read_json_dict(resolved)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Abweichungsregeln '{resolved}' enthalten ungültiges JSON: {exc}"
        ) from exc
    return validate_deviation_rules_document(data, source=resolved)
