"""Tests für Regeldatei und Auswertung (Szenarien S1–S10)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

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

RULES_PATH = Path("share/config") / "deviation_rules.example.json"


@pytest.fixture
def rules_doc() -> dict:
    return load_deviation_rules(str(RULES_PATH))


def _closed_battery_mean(slot: datetime, battery_kw: float) -> dict:
    from optimizer.schedule import quarter_hour_slot_start

    return {
        quarter_hour_slot_start(slot): {
            "sample_count": 10,
            "battery_kw": battery_kw,
        }
    }


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

    def test_s2_ev_error(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"ev": 3.5},
            consumption_snapshot={"flex_kw": {"ev": 0.0}, "battery_kw": 0.0},
            charging_contexts={"ev": {"plugged_in": True, "active": True}},
            consumer_remaining_kwh={"ev": 8.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].rule_id == "ev_should_charge"
        assert "3.50" in events[0].message

    def test_s3_forced_charge_error(self, rules_doc):
        slot = datetime(2026, 10, 30, 1, 15)
        entry = _entry(
            mode=bat.MODE_ZWANGS_LADEN,
            target_power_kw=2.5,
            battery_plan_kw=2.5,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(
            entry,
            rules_doc=rules_doc,
            slot_start=slot,
            closed_by_interval=_closed_battery_mean(slot, 0.0),
        )
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].scope == "battery"
        assert events[0].rule_id == "battery_forced_charge_missing"
        assert "0 %" in events[0].message
        assert "0.62 kWh" in events[0].message

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

    def test_forced_discharge_partial_delivery_not_missing(self, rules_doc):
        """Mean Ist short of Soll is still 'executed' — not S6 'entlädt nicht'."""
        entry = _entry(
            mode=bat.MODE_ZWANGS_ENTLADEN,
            target_power_kw=3.317,
            battery_plan_kw=-3.317,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 2.844},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert events == []

    @staticmethod
    def _forced_charge_events(rules_doc, mean_battery_kw, *, soll_kw=2.0):
        slot = datetime(2026, 10, 30, 1, 15)
        entry = _entry(
            mode=bat.MODE_ZWANGS_LADEN,
            target_power_kw=soll_kw,
            battery_plan_kw=soll_kw,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 2.25},
            completed_at="2026-10-30T01:15:02",
        )
        return evaluate_entry_deviations(
            entry,
            rules_doc=rules_doc,
            slot_start=slot,
            closed_by_interval=_closed_battery_mean(slot, mean_battery_kw),
        )

    def test_forced_charge_energy_below_80_percent_is_yellow_warning(self, rules_doc):
        # Loxone: negative = charge; 1.4 of 2.0 kW over the slot = 70 % energy.
        events = self._forced_charge_events(rules_doc, -1.4)
        assert len(events) == 1
        assert events[0].category == "warning"
        assert events[0].rule_id == "battery_forced_charge_target_missed"
        assert events[0].color == "#f1c40f"
        assert "70 %" in events[0].message
        assert "Soll 0.50 kWh" in events[0].message
        assert "Ist 0.35 kWh" in events[0].message

    def test_forced_charge_energy_at_80_percent_is_ok(self, rules_doc):
        assert self._forced_charge_events(rules_doc, -1.6) == []

    def test_forced_charge_energy_at_60_percent_is_warning(self, rules_doc):
        events = self._forced_charge_events(rules_doc, -1.2)
        assert [e.rule_id for e in events] == ["battery_forced_charge_target_missed"]

    def test_forced_charge_energy_below_60_percent_is_error(self, rules_doc):
        events = self._forced_charge_events(rules_doc, -1.0)
        assert [e.category for e in events] == ["error"]
        assert events[0].rule_id == "battery_forced_charge_missing"
        assert "50 %" in events[0].message

    def test_forced_charge_discharging_slot_mean_is_error(self, rules_doc):
        """Dump 30.10. 01:15: forced charge 0.213 kW, slot mean still discharging."""
        events = self._forced_charge_events(rules_doc, 0.266, soll_kw=0.213)
        assert [e.rule_id for e in events] == ["battery_forced_charge_missing"]

    def test_forced_charge_without_slot_mean_has_no_energy_verdict(self, rules_doc):
        """A decision-time sample is not slot energy — no forced-charge marker."""
        entry = _entry(
            mode=bat.MODE_ZWANGS_LADEN,
            target_power_kw=2.5,
            battery_plan_kw=2.5,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 0.0},
        )
        assert evaluate_entry_deviations(entry, rules_doc=rules_doc) == []

    def test_energy_ratio_predicate_requires_max_ratio(self, rules_doc):
        doc = json.loads(json.dumps(rules_doc))
        for rule in doc["rules"]:
            if rule["id"] == "battery_forced_charge_missing":
                del rule["params"]
        with pytest.raises(ValueError, match="max_ratio"):
            self._forced_charge_events(doc, 0.0)

    def test_s2b_ev_pv_follow_error(self, rules_doc, monkeypatch):
        ev_consumer = {
            "id": "ev",
            "name": "E-Auto",
            "nominal_power_kw": 3.5,
            "min_power_kw": 1.4,
            "ehal_bindings": {
                "set_evcs_max_current": "Earnie_EAuto_Soll_A",
                "set_evcs_mode": "Earnie_EAuto_Modus",
            },
        }
        monkeypatch.setattr(
            facts_mod.config, "get_flexible_consumers", lambda **kw: [ev_consumer]
        )
        entry = _entry(
            consumer_powers_kw={"ev": 2.0},
            consumer_pv_follow={"ev": 1},
            consumption_snapshot={"flex_kw": {"ev": 0.0}, "battery_kw": 0.0},
            charging_contexts={"ev": {"plugged_in": True, "active": True}},
            consumer_remaining_kwh={"ev": 8.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].rule_id == "ev_pv_follow_missing"
        assert "3.50" in events[0].message

    def test_s4_no_deviation_within_tolerance(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"swimspa": 2.0},
            consumption_snapshot={"flex_kw": {"swimspa": 2.02}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert events == []

    def test_s5_wp_heating_hint(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"wp_heating": 1.5},
            consumption_snapshot={"flex_kw": {"wp_heating": 0.0}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "hint"
        assert events[0].rule_id == "wp_heating_enable_no_start"
        assert "1.50" in events[0].message

    def test_missing_slot_quality_skips_evaluation(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"ev": 3.5},
            consumption_snapshot={"flex_kw": {"ev": 0.0}, "battery_kw": 0.0},
            charging_contexts={"ev": {"plugged_in": True}},
            consumer_remaining_kwh={"ev": 8.0},
        )
        facts = build_slot_deviation_facts(entry, slot_quality=SLOT_MISSING)
        assert evaluate_slot_deviations(facts, rules_doc) == []

    def test_present_slot_required_by_default(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"ev": 3.5},
            consumption_snapshot={"flex_kw": {"ev": 0.0}, "battery_kw": 0.0},
            charging_contexts={"ev": {"plugged_in": True}},
            consumer_remaining_kwh={"ev": 8.0},
        )
        facts = build_slot_deviation_facts(entry, slot_quality=SLOT_PRESENT)
        events = evaluate_slot_deviations(facts, rules_doc)
        assert len(events) == 1


class TestSwimspaFilterRules:
    """Szenarien S8–S10 für den ergänzenden SwimSpa-Filter (Backlog Z.17)."""

    @pytest.fixture
    def with_filter_consumer(self, monkeypatch):
        """swimspa_filter mit Nennleistung 0,18 kW für den Facts-Lookup bereitstellen."""
        consumer = {"id": "pool_filter", "name": "SwimSpa Filter", "nominal_power_kw": 0.18}

        def _fake_consumer_config(consumer_id: str):
            return consumer if consumer_id == "pool_filter" else None

        monkeypatch.setattr(facts_mod, "_consumer_config", _fake_consumer_config)

    def test_s8_should_run_but_missing(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"pool_filter": 0.18},
            consumption_snapshot={"flex_kw": {"pool_filter": 0.0}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
        assert len(events) == 1
        assert events[0].category == "error"
        assert events[0].rule_id == "swimspa_filter_should_run_missing"

    def test_s9_runs_unexpectedly_outside_native_window(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"pool_filter": 0.0},
            consumption_snapshot={"flex_kw": {"pool_filter": 0.18}, "battery_kw": 0.0},
            filter_contexts={
                "pool_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
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
            consumer_powers_kw={"pool_filter": 0.0},
            consumption_snapshot={"flex_kw": {"pool_filter": 0.18}, "battery_kw": 0.0},
            filter_contexts={
                "pool_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
            },
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 11, 0)
        )
        assert events == []

    def test_s9c_no_window_info_is_conservative(self, rules_doc):
        entry = _entry(
            consumer_powers_kw={"pool_filter": 0.0},
            consumption_snapshot={"flex_kw": {"pool_filter": 0.18}, "battery_kw": 0.0},
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 15, 0)
        )
        assert events == []

    def test_s10_over_nominal_warning(self, rules_doc, with_filter_consumer):
        entry = _entry(
            consumer_powers_kw={"pool_filter": 0.18},
            consumption_snapshot={"flex_kw": {"pool_filter": 0.40}, "battery_kw": 0.0},
            filter_contexts={
                "pool_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
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
            consumer_powers_kw={"pool_filter": 0.18},
            consumption_snapshot={"flex_kw": {"pool_filter": 0.40}, "battery_kw": 0.0},
            filter_contexts={
                "pool_filter": {"native_start_hour": 10, "native_duration_hours": 4.0}
            },
        )
        events = evaluate_entry_deviations(
            entry, rules_doc=rules_doc, slot_start=datetime(2026, 7, 7, 11, 0)
        )
        assert events == []


class TestRuleLevelTolerance:
    def test_rule_power_kw_overrides_global(self, rules_doc):
        rules_doc = dict(rules_doc)
        rules_doc["tolerances"] = {"power_kw": 0.05}
        rules_doc["rules"] = [
            {
                "id": "eauto_custom_tol",
                "enabled": True,
                "category": "error",
                "priority": 50,
                "scope": "eauto",
                "when": ["power_mismatch_positive", "plugged_in"],
                "params": {"power_kw": 0.5},
                "message": "E-Auto: Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW",
            }
        ]
        entry = _entry(
            consumer_powers_kw={"eauto": 2.5},
            consumption_snapshot={"flex_kw": {"eauto": 2.0}, "battery_kw": 0.0},
            charging_contexts={"eauto": {"plugged_in": True}},
        )
        facts = build_slot_deviation_facts(entry)
        events = evaluate_slot_deviations(facts, rules_doc)
        assert events == []

        rules_doc["rules"][0]["params"] = {"power_kw": 0.1}
        events = evaluate_slot_deviations(facts, rules_doc)
        assert len(events) == 1
        assert events[0].rule_id == "eauto_custom_tol"


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
