"""Tests für Regeldatei und Auswertung (Szenarien S1–S10)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer import battery as bat
from optimizer import deviation_facts as facts_mod
from optimizer.deviation_eval import (
    evaluate_entry_deviations,
    evaluate_slot_deviations,
    format_deviation_message,
)
from optimizer.deviation_facts import build_slot_deviation_facts
from optimizer.deviation_rules import load_deviation_rules, validate_deviation_rules_document
from runtime_store.history_timeline import SLOT_MISSING, SLOT_PRESENT

RULES_PATH = Path("config") / "deviation_rules.example.json"


@pytest.fixture
def rules_doc() -> dict:
    return load_deviation_rules(str(RULES_PATH))


def _entry(**extra) -> dict:
    base = {
        "completed_at": "2026-07-05T10:00:00",
        "success": True,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "battery_plan_kw": 0.0,
        "consumption_snapshot": {"flex_kw": {}, "battery_kw": 0.0},
        "consumer_powers_kw": {},
        "charging_contexts": {},
        "consumer_remaining_kwh": {},
        "thermal_observability": [],
    }
    base.update(extra)
    return base


class TestDeviationRulesLoader:
    def test_load_example_rules(self, rules_doc):
        assert rules_doc["version"] == 1
        assert len(rules_doc["rules"]) >= 5

    def test_rejects_unknown_category(self):
        data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        data["rules"][0]["category"] = "critical"
        with pytest.raises(ValueError, match="category"):
            validate_deviation_rules_document(data, source="test")


class TestMessageFormatting:
    def test_format_with_precision(self):
        text = format_deviation_message(
            "Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW",
            {"soll_kw": 3.456, "ist_kw": 0.0},
        )
        assert text == "Soll 3.46 kW, Ist 0.00 kW"


class TestScenarioCatalog:
    def test_s1_swimspa_warning(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"swimspa": 2.8},
            consumption_snapshot={"flex_kw": {"swimspa": 0.0}, "battery_kw": 0.0},
            thermal_observability=[
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
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "warning"
        assert events[0].rule_id == "swimspa_thermal_band_ok"

    def test_s2_eauto_error(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"eauto": 3.5},
            consumption_snapshot={"flex_kw": {"eauto": 0.0}, "battery_kw": 0.0},
            charging_contexts={"eauto": {"plugged_in": True, "active": True}},
            consumer_remaining_kwh={"eauto": 8.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].rule_id == "eauto_should_charge"
        assert "3.50" in events[0].message

    def test_s3_forced_charge_error(self, rules_doc):
        entry = _entry(
            mode=bat.MODE_ZWANGS_LADEN,
            target_power_kw=2.5,
            battery_plan_kw=2.5,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].scope == "battery"
        assert events[0].rule_id == "battery_forced_charge_missing"

    def test_s3b_forced_discharge_error(self, rules_doc):
        entry = _entry(
            mode=bat.MODE_ZWANGS_ENTLADEN,
            target_power_kw=2.0,
            battery_plan_kw=-2.0,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].scope == "battery"
        assert events[0].rule_id == "battery_forced_discharge_missing"

    def test_s2b_eauto_pv_follow_error(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"eauto": 2.0},
            consumer_pv_follow={"eauto": 1},
            loxone_sent={
                "Ernie_EAuto_Ziel_kW": 3.5,
                "Ernie_EAuto_pv_follow": 1.0,
            },
            consumption_snapshot={"flex_kw": {"eauto": 0.0}, "battery_kw": 0.0},
            charging_contexts={"eauto": {"plugged_in": True, "active": True}},
            consumer_remaining_kwh={"eauto": 8.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].rule_id == "eauto_pv_follow_missing"
        assert "3.50" in events[0].message

    def test_s4_no_deviation_within_tolerance(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"swimspa": 2.0},
            consumption_snapshot={"flex_kw": {"swimspa": 2.02}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert events == []

    def test_s5_waermepumpe_hint(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"waermepumpe": 1.5},
            consumption_snapshot={"flex_kw": {"waermepumpe": 0.0}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "hint"
        assert events[0].rule_id == "waermepumpe_enable_no_start"
        assert "1.50" in events[0].message

    def test_missing_slot_quality_skips_evaluation(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"eauto": 3.5},
            consumption_snapshot={"flex_kw": {"eauto": 0.0}, "battery_kw": 0.0},
            charging_contexts={"eauto": {"plugged_in": True}},
            consumer_remaining_kwh={"eauto": 8.0},
        )
        facts = build_slot_deviation_facts(entry, slot_quality=SLOT_MISSING)
        assert evaluate_slot_deviations(facts, rules_doc) == []

    def test_present_slot_required_by_default(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"eauto": 3.5},
            consumption_snapshot={"flex_kw": {"eauto": 0.0}, "battery_kw": 0.0},
            charging_contexts={"eauto": {"plugged_in": True}},
            consumer_remaining_kwh={"eauto": 8.0},
        )
        facts = build_slot_deviation_facts(entry, slot_quality=SLOT_PRESENT)
        events = evaluate_slot_deviations(facts, rules_doc)
        assert len(events) == 1


class TestSwimspaFilterRules:
    """Szenarien S8–S10 für den ergänzenden SwimSpa-Filter (Backlog Z.17)."""

    @pytest.fixture
    def with_filter_consumer(self, monkeypatch):
        """swimspa_filter mit Nennleistung 0,18 kW für den Facts-Lookup bereitstellen."""
        consumer = {"id": "swimspa_filter", "name": "SwimSpa Filter", "nominal_power_kw": 0.18}

        def _fake_consumer_config(consumer_id: str):
            return consumer if consumer_id == "swimspa_filter" else None

        monkeypatch.setattr(facts_mod, "_consumer_config", _fake_consumer_config)

    def test_s8_should_run_but_missing(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"swimspa_filter": 0.18},
            consumption_snapshot={"flex_kw": {"swimspa_filter": 0.0}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].rule_id == "swimspa_filter_should_run_missing"

    def test_s9_runs_unexpectedly_outside_native_window(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"swimspa_filter": 0.0},
            consumption_snapshot={"flex_kw": {"swimspa_filter": 0.18}, "battery_kw": 0.0},
            filter_contexts={
                "swimspa_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
            },
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 15, 0)
        )
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].rule_id == "swimspa_filter_runs_unexpectedly"

    def test_s9b_native_run_inside_window_no_event(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"swimspa_filter": 0.0},
            consumption_snapshot={"flex_kw": {"swimspa_filter": 0.18}, "battery_kw": 0.0},
            filter_contexts={
                "swimspa_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
            },
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 11, 0)
        )
        assert events == []

    def test_s9c_no_window_info_is_conservative(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"swimspa_filter": 0.0},
            consumption_snapshot={"flex_kw": {"swimspa_filter": 0.18}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 15, 0)
        )
        assert events == []

    def test_s10_over_nominal_warning(self, rules_doc, with_filter_consumer):
        entry = _entry(
            consumer_powers_kw={"swimspa_filter": 0.18},
            consumption_snapshot={"flex_kw": {"swimspa_filter": 0.40}, "battery_kw": 0.0},
            filter_contexts={
                "swimspa_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
            },
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 11, 0)
        )
        assert len(events) == 1
        assert events[0].category == "warning"
        assert events[0].rule_id == "swimspa_filter_over_nominal"
        assert "0.40" in events[0].message

    def test_over_nominal_without_config_does_not_fire(self, rules_doc):
        """Ohne bekannte Nennleistung (Consumer nicht in Config) keine Warnung."""
        entry = _entry(
            consumer_powers_kw={"swimspa_filter": 0.18},
            consumption_snapshot={"flex_kw": {"swimspa_filter": 0.40}, "battery_kw": 0.0},
            filter_contexts={
                "swimspa_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
            },
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 11, 0)
        )
        assert events == []


class TestPredicateErrors:
    def test_unknown_predicate_raises(self, rules_doc):
        rules_doc = dict(rules_doc)
        rules_doc["rules"] = [
            {
                "id": "broken_rule",
                "enabled": True,
                "category": "error",
                "priority": 1,
                "scope": "eauto",
                "when": ["does_not_exist"],
                "message": "x",
            }
        ]
        entry = _entry(consumer_powers_kw={"eauto": 2.0})
        facts = build_slot_deviation_facts(entry)
        with pytest.raises(ValueError, match="Unbekanntes Prädikat"):
            evaluate_slot_deviations(facts, rules_doc)
