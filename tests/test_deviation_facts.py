"""Tests für optimizer/deviation_facts.py."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer import battery as bat
from optimizer.deviation_facts import build_slot_deviation_facts


def test_build_facts_flex_soll_and_ist():
    entry = {
        "consumer_powers_kw": {"swimspa": 2.8, "eauto": 3.5},
        "consumption_snapshot": {
            "flex_kw": {"swimspa": 0.0, "eauto": 3.48},
            "battery_kw": -1.2,
        },
        "mode": bat.MODE_AUTOMATIK,
    }
    facts = build_slot_deviation_facts(entry)
    assert facts.consumers["swimspa"].soll_kw == pytest.approx(2.8)
    assert facts.consumers["swimspa"].ist_kw == pytest.approx(0.0)
    assert facts.consumers["eauto"].ist_kw == pytest.approx(3.48)
    assert facts.battery.ist_power_kw == pytest.approx(-1.2)
    assert facts.battery.soll_plan_kw == pytest.approx(0.0)


def test_build_facts_prefers_snapshot_flex_over_live():
    entry = {
        "consumer_powers_kw": {"eauto": 2.0},
        "flex_live_kw": {"eauto": 9.9},
        "consumption_snapshot": {"flex_kw": {"eauto": 1.5}},
    }
    facts = build_slot_deviation_facts(entry)
    assert facts.consumers["eauto"].ist_kw == pytest.approx(1.5)


def test_build_facts_thermal_and_charging_context():
    entry = {
        "consumer_powers_kw": {"swimspa": 2.0},
        "thermal_observability": [
            {
                "consumer_id": "swimspa",
                "heating_hours": 2,
                "heating_schedule": [0, 5],
                "readings_c": {"actual": 36.5, "band_min": 35.5, "band_max": 37.5},
            }
        ],
        "charging_contexts": {"eauto": {"plugged_in": True}},
        "consumer_remaining_kwh": {"eauto": 7.5},
    }
    facts = build_slot_deviation_facts(entry)
    thermal = facts.thermal["swimspa"]
    assert thermal.actual_c == pytest.approx(36.5)
    assert thermal.heating_scheduled is True
    assert facts.charging_contexts["eauto"]["plugged_in"] is True
    assert facts.consumer_remaining_kwh["eauto"] == pytest.approx(7.5)


def test_build_facts_forced_charge_battery_plan():
    entry = {
        "mode": bat.MODE_ZWANGS_LADEN,
        "target_power_kw": 2.5,
        "battery_plan_kw": 2.5,
        "consumption_snapshot": {"battery_kw": 0.0},
    }
    facts = build_slot_deviation_facts(entry)
    assert facts.battery.soll_mode == bat.MODE_ZWANGS_LADEN
    assert facts.battery.soll_plan_kw == pytest.approx(2.5)
