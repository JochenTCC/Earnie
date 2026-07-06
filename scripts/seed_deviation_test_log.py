#!/usr/bin/env python3
"""
Erzeugt ein fiktives Produktiv-Log zum Testen der Soll/Ist-Abweichungsregeln.

Die letzten sieben Einträge entsprechen dem Szenario-Katalog S1–S7
(docs/spec/soll-ist-abweichung.md inkl. Zwangs-Entladen und pv_follow).
Davor liegen neutrale Baseline-Slots.
Zeitstempel werden auf aufeinanderfolgende 15-Min-Slots bis kurz vor den
Live-Anker gelegt (analog seed_history_test_logs.py).

Aufruf:
    python -m scripts.seed_deviation_test_log --force
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from optimizer import battery as bat
from optimizer.deviation_eval import evaluate_entry_deviations
from optimizer.deviation_rules import load_deviation_rules
from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start
from scripts.seed_history_test_logs import _remap_entries, _write_jsonl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "runtime" / "optimization_history.jsonl"
RULES_PATH = ROOT / "config" / "deviation_rules.json"

SCENARIO_LABELS = (
    "S1_swimspa_warning",
    "S2_eauto_error",
    "S3_battery_forced_charge",
    "S6_battery_forced_discharge",
    "S7_eauto_pv_follow",
    "S4_within_tolerance",
    "S5_waermepumpe_hint",
)


def _flex_snapshot(
    *,
    swimspa: float = 0.0,
    eauto: float = 0.0,
    waermepumpe: float = 0.0,
    battery_kw: float = 0.0,
) -> dict:
    flex = {"swimspa": swimspa, "eauto": eauto, "waermepumpe": waermepumpe}
    flex_sum = round(sum(flex.values()), 3)
    baseload = 0.65
    pv = 1.2
    house = round(baseload + flex_sum, 3)
    return {
        "house_kw": house,
        "baseload_kw": baseload,
        "flex_kw": flex,
        "flex_sum_kw": flex_sum,
        "pv_kw": pv,
        "grid_kw": round(house - pv - battery_kw, 3),
        "battery_kw": battery_kw,
    }


def _baseline_entry(index: int) -> dict:
    """Neutraler Slot ohne Abweichungs-Event."""
    soc = 72.0 - index * 0.3
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": round(soc, 1),
        "pv_delta_kwh": 0.18,
        "market_price_cent": 12.5,
        "forecast_pv_kw": 1.5,
        "forecast_consumption_kw": 0.8,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "target_soc_percent": 85.0,
        "battery_plan_kw": -0.4,
        "consumer_powers_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "flex_live_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(battery_kw=0.35),
        "charging_contexts": {},
        "consumer_remaining_kwh": {"eauto": 0.0},
        "thermal_observability": [],
        "scenario": "baseline",
    }


def _scenario_s1_swimspa_warning() -> dict:
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": 68.0,
        "market_price_cent": 11.0,
        "forecast_pv_kw": 0.8,
        "forecast_consumption_kw": 1.1,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "target_soc_percent": 85.0,
        "battery_plan_kw": -0.2,
        "consumer_powers_kw": {"swimspa": 2.8},
        "flex_live_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(swimspa=0.0, battery_kw=0.2),
        "thermal_observability": [
            {
                "consumer_id": "swimspa",
                "heating_hours": 3,
                "heating_schedule": [0, 1, 2],
                "readings_c": {
                    "actual": 36.5,
                    "band_min": 35.5,
                    "band_max": 37.5,
                },
            }
        ],
        "scenario": SCENARIO_LABELS[0],
    }


def _scenario_s2_eauto_error() -> dict:
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": 67.0,
        "market_price_cent": 10.5,
        "forecast_pv_kw": 0.5,
        "forecast_consumption_kw": 1.0,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "target_soc_percent": 85.0,
        "battery_plan_kw": 0.0,
        "consumer_powers_kw": {"eauto": 3.5},
        "flex_live_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(eauto=0.0),
        "charging_contexts": {"eauto": {"plugged_in": True, "active": True}},
        "consumer_remaining_kwh": {"eauto": 8.0},
        "thermal_observability": [],
        "scenario": SCENARIO_LABELS[1],
    }


def _scenario_s3_battery_forced_charge() -> dict:
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": 55.0,
        "market_price_cent": 8.0,
        "forecast_pv_kw": 2.0,
        "forecast_consumption_kw": 0.9,
        "mode": bat.MODE_ZWANGS_LADEN,
        "target_power_kw": 2.5,
        "target_soc_percent": 90.0,
        "battery_plan_kw": 2.5,
        "consumer_powers_kw": {},
        "flex_live_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(battery_kw=0.0),
        "thermal_observability": [],
        "scenario": SCENARIO_LABELS[2],
    }


def _scenario_s6_battery_forced_discharge() -> dict:
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": 78.0,
        "market_price_cent": 14.0,
        "forecast_pv_kw": 0.4,
        "forecast_consumption_kw": 1.0,
        "mode": bat.MODE_ZWANGS_ENTLADEN,
        "target_power_kw": 2.0,
        "target_soc_percent": 50.0,
        "battery_plan_kw": -2.0,
        "consumer_powers_kw": {},
        "flex_live_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(battery_kw=0.0),
        "thermal_observability": [],
        "scenario": SCENARIO_LABELS[3],
    }


def _scenario_s7_eauto_pv_follow() -> dict:
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": 64.0,
        "market_price_cent": 7.5,
        "forecast_pv_kw": 2.5,
        "forecast_consumption_kw": 0.7,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "target_soc_percent": 85.0,
        "battery_plan_kw": -0.5,
        "consumer_powers_kw": {"eauto": 2.0},
        "consumer_pv_follow": {"eauto": 1},
        "loxone_sent": {
            "Ernie_EAuto_Ziel_kW": 3.5,
            "Ernie_EAuto_pv_follow": 1.0,
        },
        "flex_live_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(eauto=0.0, battery_kw=0.3),
        "charging_contexts": {"eauto": {"plugged_in": True, "active": True}},
        "consumer_remaining_kwh": {"eauto": 6.0},
        "thermal_observability": [],
        "scenario": SCENARIO_LABELS[4],
    }


def _scenario_s4_within_tolerance() -> dict:
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": 66.0,
        "market_price_cent": 9.5,
        "forecast_pv_kw": 1.8,
        "forecast_consumption_kw": 0.85,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "target_soc_percent": 85.0,
        "battery_plan_kw": -0.3,
        "consumer_powers_kw": {"swimspa": 2.0},
        "flex_live_kw": {"swimspa": 2.02, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(swimspa=2.02, battery_kw=0.25),
        "thermal_observability": [],
        "scenario": SCENARIO_LABELS[5],
    }


def _scenario_s5_waermepumpe_hint() -> dict:
    return {
        "source": "seed_deviation_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": 65.0,
        "market_price_cent": 9.0,
        "forecast_pv_kw": 1.2,
        "forecast_consumption_kw": 0.9,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "target_soc_percent": 85.0,
        "battery_plan_kw": -0.1,
        "consumer_powers_kw": {"waermepumpe": 1.5},
        "flex_live_kw": {"swimspa": 0.0, "eauto": 0.0, "waermepumpe": 0.0},
        "consumption_snapshot": _flex_snapshot(waermepumpe=0.0),
        "thermal_observability": [],
        "scenario": SCENARIO_LABELS[6],
    }


def build_deviation_test_entries(*, baseline_count: int) -> list[dict]:
    if baseline_count < 0:
        raise ValueError("baseline_count muss >= 0 sein")
    entries = [_baseline_entry(index) for index in range(baseline_count)]
    entries.extend(
        [
            _scenario_s1_swimspa_warning(),
            _scenario_s2_eauto_error(),
            _scenario_s3_battery_forced_charge(),
            _scenario_s6_battery_forced_discharge(),
            _scenario_s7_eauto_pv_follow(),
            _scenario_s4_within_tolerance(),
            _scenario_s5_waermepumpe_hint(),
        ]
    )
    return entries


def _validate_scenarios(entries: list[dict], rules_doc: dict) -> None:
    scenarios = entries[-7:]
    expectations = [
        (1, "warning", "swimspa_thermal_band_ok"),
        (1, "error", "eauto_should_charge"),
        (1, "error", "battery_forced_charge_missing"),
        (1, "error", "battery_forced_discharge_missing"),
        (1, "error", "eauto_pv_follow_missing"),
        (0, None, None),
        (1, "hint", "waermepumpe_enable_no_start"),
    ]
    for entry, (expected_count, category, rule_id) in zip(scenarios, expectations):
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        if len(events) != expected_count:
            label = entry.get("scenario", "?")
            raise ValueError(
                f"{label}: erwartet {expected_count} Event(s), "
                f"bekam {len(events)} ({events!r})"
            )
        if expected_count == 1:
            assert events[0].category == category
            assert events[0].rule_id == rule_id


def seed_deviation_test_log(
    target: Path,
    *,
    anchor: datetime | None = None,
    baseline_count: int = 8,
    rules_path: Path = RULES_PATH,
) -> dict:
    rules_doc = load_deviation_rules(str(rules_path))
    entries = build_deviation_test_entries(baseline_count=baseline_count)
    _validate_scenarios(entries, rules_doc)
    anchor_slot = quarter_hour_slot_start(anchor)
    remapped = _remap_entries(entries, anchor_slot)
    for row in remapped:
        row["source"] = "seed_deviation_test_log.py"
    _write_jsonl(target, remapped)
    scenario_slots = [
        {
            "scenario": row.get("scenario"),
            "slot": row["completed_at"],
            "events": [
                {
                    "category": event.category,
                    "rule_id": event.rule_id,
                    "message": event.message,
                }
                for event in evaluate_entry_deviations(row, rules_doc=rules_doc)
            ],
        }
        for row in remapped[-7:]
    ]
    return {
        "target": str(target),
        "entries": len(remapped),
        "baseline_count": baseline_count,
        "first_slot": remapped[0]["completed_at"],
        "last_slot": remapped[-1]["completed_at"],
        "anchor": anchor_slot.isoformat(timespec="seconds"),
        "scenario_slots": scenario_slots,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Ziel-jsonl (Standard: runtime/optimization_history.jsonl)",
    )
    parser.add_argument(
        "--baseline-count",
        type=int,
        default=8,
        help="Anzahl neutraler Slots vor den sieben Szenarien (Standard: 8 = 2 h)",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=RULES_PATH,
        help="Regeldatei zur Validierung (Standard: config/deviation_rules.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bestehende Zieldatei überschreiben",
    )
    args = parser.parse_args()

    if args.target.is_file() and not args.force:
        raise SystemExit(
            f"Zieldatei existiert bereits: {args.target}\n"
            "Zum Überschreiben --force angeben."
        )
    if args.target.is_file() and args.force:
        backup = args.target.with_suffix(".jsonl.bak")
        shutil.copy2(args.target, backup)
        print(f"Backup: {backup}")

    summary = seed_deviation_test_log(
        args.target,
        baseline_count=args.baseline_count,
        rules_path=args.rules,
    )
    print(
        f"{summary['entries']} Eintraege nach {summary['target']} geschrieben\n"
        f"Slots: {summary['first_slot']} -> {summary['last_slot']} "
        f"(Anker {summary['anchor']})"
    )
    print("\nSzenario-Slots (letzte 7):")
    for item in summary["scenario_slots"]:
        events = item["events"]
        if events:
            detail = f"{events[0]['category']} / {events[0]['rule_id']}"
        else:
            detail = "kein Icon (erwartet)"
        print(f"  {item['slot']}  {item['scenario']}: {detail}")


if __name__ == "__main__":
    main()
