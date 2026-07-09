"""Backtesting-Szenarien laden und normalisieren."""
from __future__ import annotations

import json
import os

from settings.json_io import read_json_dict


def load_backtesting_scenarios_document(backtesting_scenarios_path: str) -> dict:
    path = backtesting_scenarios_path
    if not os.path.isfile(path):
        return {}
    return read_json_dict(path)


def load_backtesting_scenarios_entries(
    backtesting_scenarios_path: str,
    raw_config: dict,
) -> list:
    path = backtesting_scenarios_path
    if os.path.isfile(path):
        try:
            data = read_json_dict(path)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Kritischer Fehler: '{path}' enthält ungültiges JSON: {e}"
            ) from e
        raw = data.get("scenarios")
        if raw is None:
            raise KeyError(
                f"Kritischer Konfigurationsfehler: '{path}' benötigt ein "
                "'scenarios'-Array."
            )
        if not isinstance(raw, list):
            raise ValueError(
                f"Kritischer Konfigurationsfehler: '{path}': scenarios muss ein Array sein."
            )
        return raw

    raw = raw_config.get("scenarios")
    if isinstance(raw, list) and raw:
        return raw

    legacy = {
        key: value
        for key, value in raw_config.items()
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


def normalize_scenario(raw: dict, index: int) -> dict:
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


def get_backtesting_cbc_gap_rel(backtesting_scenarios_path: str) -> float:
    """
    Relativer CBC-MIP-Gap für Backtesting aus backtesting_scenarios.json.
    Fehlt der Schlüssel, gilt optimizer.cbc_solver.DEFAULT_CBC_GAP_REL.
    """
    from optimizer.cbc_solver import DEFAULT_CBC_GAP_REL

    doc = load_backtesting_scenarios_document(backtesting_scenarios_path)
    raw = doc.get("cbc_gap_rel")
    if raw is None:
        return DEFAULT_CBC_GAP_REL
    gap = float(raw)
    if not 0.0 < gap < 1.0:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: cbc_gap_rel muss zwischen 0 und 1 liegen, "
            f"nicht {gap!r} in '{backtesting_scenarios_path}'."
        )
    return gap


def get_backtesting_cbc_strict_time_limit_sec(backtesting_scenarios_path: str) -> float:
    """
    Zeitlimit (Sekunden) für den Strict-CBC-Versuch vor gapRel-Fallback.
    Fehlt der Schlüssel, gilt optimizer.cbc_solver.DEFAULT_CBC_STRICT_TIME_LIMIT_SEC.
    0 = Strict-Stufe überspringen.
    """
    from optimizer.cbc_solver import DEFAULT_CBC_STRICT_TIME_LIMIT_SEC

    doc = load_backtesting_scenarios_document(backtesting_scenarios_path)
    raw = doc.get("cbc_strict_time_limit_sec")
    if raw is None:
        return DEFAULT_CBC_STRICT_TIME_LIMIT_SEC
    limit = float(raw)
    if limit < 0:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: cbc_strict_time_limit_sec muss >= 0 sein, "
            f"nicht {limit!r} in '{backtesting_scenarios_path}'."
        )
    return limit
