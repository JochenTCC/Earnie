#!/usr/bin/env python3
"""Fügt swimspa_filter in eine bestehende config.json ein (idempotent).

Aufruf:
    .venv\Scripts\python.exe -m scripts.patch_swimspa_filter_config
    .venv\Scripts\python.exe -m scripts.patch_swimspa_filter_config --config path/to/config.json
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


def patch_config(data: dict) -> bool:
    consumers = data.get("flexible_consumers")
    if not isinstance(consumers, list):
        raise ValueError("flexible_consumers fehlt oder ist kein Array.")
    patched, changed = patch_flexible_consumers(consumers)
    if changed:
        data["flexible_consumers"] = patched
    return changed


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
        print(f"OK: swimspa_filter bereits in {path}")
        return 0

    _save_config(path, data)
    print(f"OK: swimspa_filter in {path} eingefügt (nach swimspa).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
