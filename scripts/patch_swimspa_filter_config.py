#!/usr/bin/env python3
"""Fügt swimspa_filter in eine bestehende config.json ein (idempotent).

Aufruf:
    .venv/Scripts/python.exe -m scripts.patch_swimspa_filter_config
    .venv/Scripts/python.exe -m scripts.patch_swimspa_filter_config --config path/to/config.json
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SWIMSPA_FILTER_BLOCK = {
    "id": "swimspa_filter",
    "name": "SwimSpa Filter",
    "chart_color_index": 1,
    "nominal_power_kw": 0.18,
    "daily_target_kwh": 0.36,
    "daily_target_source": "loxone_remaining_hours",
    "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
    "signal_type": "binary",
    "min_on_quarterhours": 2,
    "optimizer_enabled": True,
    "loxone_outputs": {
        "enable_name": "Ernie_Swimspa_Filter_Freigabe",
    },
    "loxone_inputs": {
        "power_name": "homie_bwa_spa_filter2",
        "alternate_binary_power_name": "homie_bwa_spa_filter1",
        "signal_type": "binary",
    },
    "filter_schedule": {
        "enabled": True,
        "loxone": {
            "native_start_hour_name": "homie_bwa_spa_filter1hour",
            "native_duration_hours_name": "homie_bwa_spa_filter1durationhours",
        },
        "config_fallback": {
            "native_start_hour": 10,
            "native_duration_hours": 4.0,
        },
    },
}


def _default_config_path() -> Path:
    return ROOT / "config" / "config.json"


def _load_config(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"config.json nicht gefunden: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_config(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def patch_flexible_consumers(consumers: list) -> tuple[list, bool]:
    updated = list(consumers)
    for item in updated:
        if item.get("id") == "swimspa_filter":
            return updated, False

    insert_at = len(updated)
    for idx, item in enumerate(updated):
        if item.get("id") == "swimspa":
            insert_at = idx + 1
            break
    updated.insert(insert_at, deepcopy(SWIMSPA_FILTER_BLOCK))
    return updated, True


def patch_native_filter_signal(consumers: list) -> bool:
    """Ergänzt homie_bwa_spa_filter1 als alternate_binary_power_name (idempotent)."""
    for item in consumers:
        if item.get("id") != "swimspa_filter":
            continue
        inputs = item.setdefault("loxone_inputs", {})
        if inputs.get("alternate_binary_power_name") == "homie_bwa_spa_filter1":
            return False
        inputs["alternate_binary_power_name"] = "homie_bwa_spa_filter1"
        return True
    return False


def patch_swimspa_shared_meter(consumers: list) -> bool:
    """Fall B: SwimSpa-Heizungszähler misst Heizung + Filter — Filter abziehen.

    Ergänzt swimspa.loxone_inputs.subtract_consumer_ids um 'swimspa_filter'
    (idempotent). Gibt True zurück, wenn etwas geändert wurde.
    """
    for item in consumers:
        if item.get("id") != "swimspa":
            continue
        inputs = item.setdefault("loxone_inputs", {})
        subtract = inputs.get("subtract_consumer_ids")
        if not isinstance(subtract, list):
            subtract = []
        if "swimspa_filter" in subtract:
            return False
        subtract.append("swimspa_filter")
        inputs["subtract_consumer_ids"] = subtract
        return True
    return False


def patch_swimspa_heating_indicator(consumers: list) -> bool:
    """Ergänzt homie_bwa_spa_heating als thermal_control.loxone.heating_active_name (idempotent)."""
    for item in consumers:
        if item.get("id") != "swimspa":
            continue
        thermal = item.setdefault("thermal_control", {})
        loxone = thermal.setdefault("loxone", {})
        if loxone.get("heating_active_name") == "homie_bwa_spa_heating":
            return False
        loxone["heating_active_name"] = "homie_bwa_spa_heating"
        return True
    return False


def patch_config(data: dict) -> bool:
    consumers = data.get("flexible_consumers")
    if not isinstance(consumers, list):
        raise ValueError("flexible_consumers fehlt oder ist kein Array.")
    patched, changed = patch_flexible_consumers(consumers)
    if changed:
        data["flexible_consumers"] = patched
    meter_changed = patch_swimspa_shared_meter(data["flexible_consumers"])
    signal_changed = patch_native_filter_signal(data["flexible_consumers"])
    heating_changed = patch_swimspa_heating_indicator(data["flexible_consumers"])
    return changed or meter_changed or signal_changed or heating_changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="Pfad zur config.json (Standard: config/config.json)",
    )
    args = parser.parse_args()
    path = args.config.resolve()

    try:
        data = _load_config(path)
    except FileNotFoundError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        print(
            "Tipp: config/config.json aus config.example.json kopieren oder "
            "--config angeben.",
            file=sys.stderr,
        )
        return 2

    try:
        changed = patch_config(data)
    except ValueError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2

    if not changed:
        print(f"OK: swimspa_filter + Shared-Meter-Abzug bereits in {path}")
        return 0

    _save_config(path, data)
    print(
        f"OK: {path} aktualisiert — swimspa_filter vorhanden und "
        "swimspa.loxone_inputs.subtract_consumer_ids=['swimspa_filter'] gesetzt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
