"""Migration dm4.retire_plant_pv_binding — plant PV → inv."""
from __future__ import annotations

from ehal.inverter_fields import inv_field
from runtime_store.migration.steps.retire_plant_pv_binding import (
    STEP_ID,
    apply,
    detect,
)


def test_detect_when_plant_pv_key_present():
    docs = {
        "house_profiles.json": {
            "plant": {"ehal_bindings": {"sens_pv_production_active": "PV"}},
            "profiles": {},
        },
        "components.json": {"inverters": [], "pv_systems": [], "batteries": []},
    }
    assert detect(docs) is True
    assert STEP_ID == "dm4.retire_plant_pv_binding"


def test_apply_copies_to_sole_grid_tied_inv():
    docs = {
        "house_profiles.json": {
            "earnie_data_model": 4,
            "plant": {
                "ehal_bindings": {
                    "sens_grid_power_active": "Grid",
                    "sens_pv_production_active": "Earnie_PV",
                }
            },
            "profiles": {},
        },
        "components.json": {
            "earnie_data_model": 4,
            "batteries": [],
            "inverters": [
                {
                    "id": "wr",
                    "type": "pv_string",
                    "ac_connection": "grid_tied",
                    "efficiency": 0.97,
                    "control": "read_only",
                    "ehal_bindings": {},
                }
            ],
            "pv_systems": [
                {"id": "dach", "kwp": 5.0, "inverter_id": "wr", "ehal_bindings": {}}
            ],
        },
    }
    result = apply(docs, {})
    assert not result.blockers
    house = result.docs["house_profiles.json"]
    assert "sens_pv_production_active" not in house["plant"]["ehal_bindings"]
    inv = result.docs["components.json"]["inverters"][0]
    assert inv["ehal_bindings"][inv_field("wr", "sens_inv_power_pv")] == "Earnie_PV"


def test_apply_blocks_multi_inv():
    docs = {
        "house_profiles.json": {
            "plant": {"ehal_bindings": {"sens_pv_production_active": "PV"}},
            "profiles": {},
        },
        "components.json": {
            "batteries": [],
            "inverters": [
                {
                    "id": "wr_a",
                    "ac_connection": "grid_tied",
                    "efficiency": 1.0,
                    "ehal_bindings": {},
                },
                {
                    "id": "wr_b",
                    "ac_connection": "grid_tied",
                    "efficiency": 1.0,
                    "ehal_bindings": {},
                },
            ],
            "pv_systems": [
                {"id": "p1", "inverter_id": "wr_a", "ehal_bindings": {}},
                {"id": "p2", "inverter_id": "wr_b", "ehal_bindings": {}},
            ],
        },
    }
    result = apply(docs, {})
    assert result.blockers
    assert "mehrere" in result.blockers[0].message_de.lower() or "nicht automatisch" in (
        result.blockers[0].message_de
    )
