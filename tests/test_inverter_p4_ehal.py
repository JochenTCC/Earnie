"""Inverter P4 (EHAL): qualified ids, role load, export unconstrained formula."""
from __future__ import annotations

import pytest

from ehal import qualified_ids as q
from ehal.inverter_fields import (
    INVERTER_FIELD_KINDS,
    inv_field,
    inv_field_kind,
    is_inv_entity_scoped_field,
)
from ehal.profiles import (
    M1_EHAL_FIELDS,
    field_role_id,
    list_device_roles,
    load_device_role,
    load_loxone_recipe,
)
from optimizer.export_power_limit import (
    physical_max_export_kw,
    physical_max_export_kw_from_inverters,
)
from runtime_store.loxone_push_inbox import is_valid_ehal_id


def test_qualified_inverter_id() -> None:
    assert q.qualified_inverter_id("wr_main", "sens_inv_power_ac") == (
        "inv.wr_main.sens_inv_power_ac"
    )
    assert q.qualified_inverter_id("wr_main", "inv.wr_main.set_inv_ac_power_limit") == (
        "inv.wr_main.set_inv_ac_power_limit"
    )
    assert is_valid_ehal_id(q.qualified_inverter_id("wr_main", "get_inv_max_ac_power"))


def test_inv_field_helpers() -> None:
    assert inv_field("wr_a", "sens_inv_power_pv") == "inv.wr_a.sens_inv_power_pv"
    assert inv_field_kind("inv.wr_a.sens_inv_power_ac") == "sens_inv_power_ac"
    assert inv_field_kind("set_inv_ac_power_limit") == "set_inv_ac_power_limit"
    assert is_inv_entity_scoped_field("inv.wr_a.get_inv_max_pv_power")
    assert not is_inv_entity_scoped_field("sens_inv_power_ac")
    assert INVERTER_FIELD_KINDS <= M1_EHAL_FIELDS


def test_inverter_role_and_recipe_load() -> None:
    assert "inverter" in list_device_roles()
    role = load_device_role("inverter")
    assert role["role_id"] == "inverter"
    assert role["label"] == "Wechselrichter"
    fields = {item["field"] for item in role["ehal_fields"]}
    assert fields == {
        "sens_inv_power_ac",
        "sens_inv_power_pv",
        "get_inv_max_ac_power",
        "get_inv_max_pv_power",
        "set_inv_ac_power_limit",
        "supports_inv_power_limit",
    }
    assert all(not item.get("required") for item in role["ehal_fields"])
    recipe = load_loxone_recipe("inverter")
    assert recipe["role_id"] == "inverter"
    assert field_role_id("inv.wr_main.sens_inv_power_ac") == "inverter"


def test_export_unconstrained_per_grid_tied_inverter() -> None:
    inverters = [
        {
            "id": "wr_main",
            "ac_connection": "grid_tied",
            "max_ac_power_kw": 10.0,
            "max_pv_input_kw": 12.0,
        },
        {"id": "wr_island", "ac_connection": "island", "max_ac_power_kw": 3.0},
    ]
    # PV 15 capped by max_pv 12 + discharge 5 = 17 → min(10, 17) = 10; island ignored.
    total = physical_max_export_kw_from_inverters(
        inverters=inverters,
        pv_kwp_by_inverter={"wr_main": 15.0, "wr_island": 2.0},
        force_discharge_kw_by_inverter={"wr_main": 5.0, "wr_island": 1.0},
    )
    assert total == pytest.approx(10.0)


def test_export_unconstrained_without_max_ac_uses_uncapped_sum() -> None:
    inverters = [{"id": "wr_main", "ac_connection": "grid_tied"}]
    total = physical_max_export_kw_from_inverters(
        inverters=inverters,
        pv_kwp_by_inverter={"wr_main": 9.8},
        force_discharge_kw_by_inverter={"wr_main": 5.0},
    )
    assert total == pytest.approx(14.8)
    assert physical_max_export_kw(9.8, 5.0) == pytest.approx(14.8)


def test_live_unconstrained_uses_planning_inverters(monkeypatch) -> None:
    import config
    from optimizer.live_export_limit import live_unconstrained_export_kw

    inv = {
        "id": "wr_main",
        "ac_connection": "grid_tied",
        "max_ac_power_kw": 8.0,
        "max_pv_input_kw": 20.0,
    }
    bat = {
        "id": "house",
        "inverter_id": "wr_main",
        "max_discharge_power_kw": 5.0,
        "control": "full",
    }
    monkeypatch.setattr(config, "_planning_inverters", [inv], raising=False)
    monkeypatch.setattr(
        config,
        "_planning_pv_systems",
        [{"id": "pv1", "inverter_id": "wr_main", "pv_kwp": 12.0}],
        raising=False,
    )
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [bat])
    monkeypatch.setattr(config, "get_battery_params", lambda: bat)
    # min(8, min(12,20)+5) = min(8, 17) = 8
    assert live_unconstrained_export_kw() == pytest.approx(8.0)
