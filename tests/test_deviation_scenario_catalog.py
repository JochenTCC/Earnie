"""Parametrisierter Szenario-Katalog S1–S7 (Epic Soll-Ist P4)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer import battery as bat
from optimizer.deviation_eval import evaluate_entry_deviations
from optimizer.deviation_rules import load_deviation_rules

RULES_PATH = "config/deviation_rules.example.json"


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


SCENARIOS = [
    pytest.param(
        "S1",
        _entry(
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
        ),
        "warning",
        "swimspa_thermal_band_ok",
        id="S1_swimspa_warning",
    ),
    pytest.param(
        "S2",
        _entry(
            consumer_powers_kw={"eauto": 3.5},
            consumption_snapshot={"flex_kw": {"eauto": 0.0}, "battery_kw": 0.0},
            charging_contexts={"eauto": {"plugged_in": True, "active": True}},
            consumer_remaining_kwh={"eauto": 8.0},
        ),
        "error",
        "eauto_should_charge",
        id="S2_eauto_charge",
    ),
    pytest.param(
        "S3",
        _entry(
            mode=bat.MODE_ZWANGS_LADEN,
            target_power_kw=2.5,
            battery_plan_kw=2.5,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 0.0},
        ),
        "error",
        "battery_forced_charge_missing",
        id="S3_forced_charge",
    ),
    pytest.param(
        "S4",
        _entry(
            consumer_powers_kw={"swimspa": 2.0},
            consumption_snapshot={"flex_kw": {"swimspa": 2.02}, "battery_kw": 0.0},
        ),
        None,
        None,
        id="S4_within_tolerance",
    ),
    pytest.param(
        "S5",
        _entry(
            consumer_powers_kw={"waermepumpe": 1.5},
            consumption_snapshot={"flex_kw": {"waermepumpe": 0.0}, "battery_kw": 0.0},
        ),
        "hint",
        "waermepumpe_enable_no_start",
        id="S5_waermepumpe_hint",
    ),
    pytest.param(
        "S6",
        _entry(
            mode=bat.MODE_ZWANGS_ENTLADEN,
            target_power_kw=2.0,
            battery_plan_kw=-2.0,
            consumption_snapshot={"flex_kw": {}, "battery_kw": 0.0},
        ),
        "error",
        "battery_forced_discharge_missing",
        id="S6_forced_discharge",
    ),
    pytest.param(
        "S7",
        _entry(
            consumer_powers_kw={"eauto": 2.0},
            consumer_pv_follow={"eauto": 1},
            loxone_sent={
                "Ernie_EAuto_Ziel_kW": 3.5,
                "Ernie_EAuto_pv_follow": 1.0,
            },
            consumption_snapshot={"flex_kw": {"eauto": 0.0}, "battery_kw": 0.0},
            charging_contexts={"eauto": {"plugged_in": True, "active": True}},
            consumer_remaining_kwh={"eauto": 8.0},
        ),
        "error",
        "eauto_pv_follow_missing",
        id="S7_pv_follow",
    ),
]


@pytest.fixture
def rules_doc() -> dict:
    return load_deviation_rules(RULES_PATH)


@pytest.mark.parametrize(
    ("scenario_id", "entry", "expected_category", "expected_rule_id"),
    SCENARIOS,
)
def test_scenario_catalog(
    rules_doc: dict,
    scenario_id: str,
    entry: dict,
    expected_category: str | None,
    expected_rule_id: str | None,
) -> None:
    events = evaluate_entry_deviations(entry, rules_doc=rules_doc)
    if expected_category is None:
        assert events == [], f"{scenario_id}: erwartet kein Icon"
        return
    assert len(events) == 1, f"{scenario_id}: {events!r}"
    assert events[0].category == expected_category
    assert events[0].rule_id == expected_rule_id
