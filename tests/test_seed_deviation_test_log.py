"""Tests für scripts/seed_deviation_test_log.py"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from optimizer.deviation_eval import evaluate_entry_deviations
from optimizer.deviation_rules import load_deviation_rules
from scripts.seed_deviation_test_log import build_deviation_test_entries, seed_deviation_test_log

TZ = ZoneInfo("Europe/Vienna")
RULES_PATH = "config/deviation_rules.json"


def test_build_deviation_test_entries_scenario_count():
    entries = build_deviation_test_entries(baseline_count=3)
    assert len(entries) == 10
    assert entries[-1]["scenario"] == "S5_waermepumpe_hint"
    assert entries[-2]["scenario"] == "S4_within_tolerance"
    assert entries[-3]["scenario"] == "S7_eauto_pv_follow"
    assert entries[-4]["scenario"] == "S6_battery_forced_discharge"
    assert all(entry.get("scenario") == "baseline" for entry in entries[:3])


def test_seed_deviation_test_log_writes_expected_events(tmp_path):
    target = tmp_path / "runtime" / "optimization_history.jsonl"
    rules_doc = load_deviation_rules(RULES_PATH)
    anchor = datetime(2026, 7, 5, 14, 0, 0, tzinfo=TZ)
    summary = seed_deviation_test_log(
        target,
        anchor=anchor,
        baseline_count=2,
        rules_path=RULES_PATH,
    )

    assert summary["entries"] == 9
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["completed_at"].startswith("2026-07-05T13:45:00")

    scenarios = rows[-7:]
    expected = [
        ("warning", "swimspa_thermal_band_ok"),
        ("error", "eauto_should_charge"),
        ("error", "battery_forced_charge_missing"),
        ("error", "battery_forced_discharge_missing"),
        ("error", "eauto_pv_follow_missing"),
        None,
        ("hint", "waermepumpe_enable_no_start"),
    ]
    for row, exp in zip(scenarios, expected):
        events = evaluate_entry_deviations(row, rules_doc=rules_doc)
        if exp is None:
            assert events == []
        else:
            category, rule_id = exp
            assert len(events) == 1
            assert events[0].category == category
            assert events[0].rule_id == rule_id
