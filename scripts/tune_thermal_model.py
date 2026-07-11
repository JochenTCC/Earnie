#!/usr/bin/env python3
"""Thermisches Modell kalibrieren und gegen Historie bewerten (bei Bedarf)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from config import CONFIG_JSON_PATH
from data.thermal_backtest import backtest_heat_loss_kw_per_k, load_merged_history
from data.thermal_calibration import estimate_heat_loss_kw_per_k


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Thermisches SwimSpa-Modell: U kalibrieren, Backtest, optional in config.json schreiben"
    )
    parser.add_argument(
        "--consumer-id",
        default="swimspa",
        help="flexible_consumers.id (Standard: swimspa)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="heat_loss_kw_per_k in config.json aktualisieren",
    )
    parser.add_argument(
        "--u",
        type=float,
        default=None,
        help="U (kW/K) für Backtest statt Config-Wert",
    )
    return parser.parse_args(argv)


def _load_consumer(consumer_id: str) -> dict:
    config.reload_config()
    consumer = next(
        (c for c in config.get_flexible_consumers() if c["id"] == consumer_id),
        None,
    )
    if consumer is None:
        raise ValueError(f"Verbraucher '{consumer_id}' nicht gefunden.")
    thermal = consumer.get("thermal_control")
    if not thermal or not thermal.get("enabled"):
        raise ValueError("thermal_control.enabled fehlt.")
    return consumer


def _write_u_to_config(consumer_id: str, u_value: float) -> None:
    path = Path(CONFIG_JSON_PATH)
    data = config.Config._read_json_dict(str(path))
    for entry in data.get("flexible_consumers", []):
        if entry.get("id") != consumer_id:
            continue
        block = entry.setdefault("thermal_control", {})
        block["heat_loss_kw_per_k"] = round(float(u_value), 5)
        break
    else:
        raise ValueError(f"Verbraucher '{consumer_id}' nicht in config.json.")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        consumer = _load_consumer(args.consumer_id)
    except ValueError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    thermal = consumer["thermal_control"]
    history_logs = thermal.get("history_logs") or {}
    try:
        u_calibrated, cal_detail = estimate_heat_loss_kw_per_k(
            history_logs,
            water_volume_liters=thermal["water_volume_liters"],
            heating_power_threshold_kw=thermal["heating_power_threshold_kw"],
        )
    except (OSError, ValueError) as exc:
        print(f"Kalibrierung fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    u_current = thermal.get("heat_loss_kw_per_k")
    u_test = float(args.u) if args.u is not None else (
        float(u_current) if u_current is not None else u_calibrated
    )

    report: dict = {
        "consumer_id": args.consumer_id,
        "u_configured_kw_per_k": u_current,
        "u_calibrated_kw_per_k": round(u_calibrated, 5),
        "u_backtest_kw_per_k": round(u_test, 5),
        "calibration": cal_detail,
    }

    try:
        merged = load_merged_history(history_logs)
        report["backtest_configured"] = backtest_heat_loss_kw_per_k(
            merged,
            water_volume_liters=thermal["water_volume_liters"],
            heating_power_threshold_kw=thermal["heating_power_threshold_kw"],
            heat_loss_kw_per_k=float(u_test),
            heating_efficiency=float(thermal["heating_efficiency"]),
        )
        report["backtest_calibrated"] = backtest_heat_loss_kw_per_k(
            merged,
            water_volume_liters=thermal["water_volume_liters"],
            heating_power_threshold_kw=thermal["heating_power_threshold_kw"],
            heat_loss_kw_per_k=u_calibrated,
            heating_efficiency=float(thermal["heating_efficiency"]),
        )
    except (OSError, ValueError) as exc:
        report["backtest_error"] = str(exc)

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.apply:
        try:
            _write_u_to_config(args.consumer_id, u_calibrated)
        except (OSError, ValueError) as exc:
            print(f"config.json konnte nicht aktualisiert werden: {exc}", file=sys.stderr)
            return 1
        print(
            f"\nconfig.json aktualisiert: thermal_control.heat_loss_kw_per_k = "
            f"{round(u_calibrated, 5)}"
        )
    else:
        print(
            "\nZum Übernehmen der kalibrierten U: "
            f"python -m scripts.tune_thermal_model --apply"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
