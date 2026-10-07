"""Batch ID cleaner for dirty earnie_env components."""
from __future__ import annotations

from ehal.ess_fields import ess_field
from house_config.clean_entity_ids import (
    apply_clean_entity_ids,
    looks_like_copy_id,
    plan_clean_entity_ids,
)


def test_looks_like_copy_id():
    assert looks_like_copy_id("15_kwh_speicher_copy_3")
    assert looks_like_copy_id("dach_sued_copy")
    assert not looks_like_copy_id("garage_west")


def test_plan_skips_already_clean():
    components = {
        "batteries": [
            {"id": "garage_west", "label": "Garage West"},
        ],
        "pv_systems": [
            {"id": "carport_ost", "label": "Carport Ost", "kwp": 5.0},
        ],
    }
    assert plan_clean_entity_ids(components) == []


def test_apply_renames_battery_bindings_scenarios_and_ps_refs():
    old = "15_kwh_speicher_copy_3"
    components = {
        "batteries": [
            {
                "id": old,
                "label": "Garage West",
                "battery_capacity_kwh": 15.0,
                "battery_max_charge_power_kw": 5.0,
                "battery_max_discharge_power_kw": 5.0,
                "battery_efficiency": 0.97,
                "battery_min_soc": 10.0,
                "battery_max_soc": 100.0,
                "ehal_bindings": {
                    ess_field(old, "sens_ess_soc"): "SoC",
                },
            }
        ],
        "pv_systems": [
            {
                "id": "dach_sued_copy_2",
                "label": "Dach Süd",
                "kwp": 10.0,
                "pv_tilt": 18.0,
                "pv_azimuth": 0.0,
            }
        ],
    }
    scenarios = {
        "scenarios": [
            {
                "id": "live",
                "settings": {
                    "battery_ids": [old],
                    "pv_system_ids": ["dach_sued_copy_2"],
                },
            }
        ]
    }
    house = {
        "profiles": [
            {
                "id": "efh",
                "flexible_consumers": [
                    {
                        "id": "ps_load",
                        "appliance_recommendation": {
                            "mode": "reserve",
                            "powerstation_id": old,
                        },
                    }
                ],
            }
        ]
    }
    comp_out, scen_out, house_out, renames = apply_clean_entity_ids(
        components, scenarios, house
    )
    assert {(r.old_id, r.new_id) for r in renames} == {
        (old, "garage_west"),
        ("dach_sued_copy_2", "dach_sued"),
    }
    bat = comp_out["batteries"][0]
    assert bat["id"] == "garage_west"
    assert bat["id_locked"] is True
    assert bat["ehal_bindings"][ess_field("garage_west", "sens_ess_soc")] == "SoC"
    assert scen_out["scenarios"][0]["settings"]["battery_ids"] == ["garage_west"]
    assert scen_out["scenarios"][0]["settings"]["pv_system_ids"] == ["dach_sued"]
    rec = house_out["profiles"][0]["flexible_consumers"][0]["appliance_recommendation"]
    assert rec["powerstation_id"] == "garage_west"


def test_only_copy_skips_non_copy_mismatch():
    components = {
        "batteries": [
            {"id": "legacy_ugly", "label": "Garage West"},
            {"id": "speicher_copy_1", "label": "Keller"},
        ],
        "pv_systems": [],
    }
    planned = plan_clean_entity_ids(components, only_copy=True)
    assert len(planned) == 1
    assert planned[0].old_id == "speicher_copy_1"
    assert planned[0].new_id == "keller"
