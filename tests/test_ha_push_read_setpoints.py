"""Entity-scoped setpoint keys reach the HA push adapter (HA testbed F3)."""
from __future__ import annotations

from integrations.ha_push_read import resolve_setpoint_qid, setpoint_qualified_ids


def _docs() -> tuple[dict, dict]:
    house = {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "",
                "set_grid_export_power_limit": "",
            }
        },
        "profiles": {},
    }
    components = {
        "batteries": [
            {
                "id": "house",
                "ehal_bindings": {
                    "ess.house.sens_ess_soc": "",
                    "ess.house.set_ess_active_power": "",
                    "ess.house.set_ess_charge_power_limit": "",
                    "ess.house.set_ess_discharge_power_limit": "",
                },
            }
        ],
        "inverters": [
            {"id": "wr_main", "ehal_bindings": {"inv.wr_main.set_inv_ac_power_limit": ""}}
        ],
    }
    return house, components


def test_setpoint_index_includes_entity_scoped_keys():
    index = setpoint_qualified_ids(*_docs())
    assert index["ess.house.set_ess_charge_power_limit"] == (
        "ess.house.set_ess_charge_power_limit"
    )
    assert "ess.house.set_ess_active_power" in index
    assert "inv.wr_main.set_inv_ac_power_limit" in index
    assert index["set_grid_export_power_limit"] == "grid.meter.set_grid_export_power_limit"
    assert not any("sens_" in key for key in index)


def test_bare_ess_field_resolves_to_entity_scoped_qid():
    index = setpoint_qualified_ids(*_docs())
    assert resolve_setpoint_qid("set_ess_charge_power_limit", index) == (
        "ess.house.set_ess_charge_power_limit"
    )
    assert resolve_setpoint_qid("set_ess_discharge_power_limit", index) == (
        "ess.house.set_ess_discharge_power_limit"
    )
