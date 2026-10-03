"""2.7.c multi-ESS: battery_ids, kind, Pattern B, export unconstrained, migrate v4."""
from __future__ import annotations

import pytest

from ehal.ess_fields import ess_field, expand_ess_bindings
from house_config.battery_kind import BATTERY_KIND_ISOLATED, allows_automatik
from house_config.entity_resolution import (
    normalize_battery_ids,
    resolve_battery_into_settings,
)
from optimizer.battery import MODE_AUTOMATIK, MODE_ENTLADESPERRE, derive_control_from_milp_plan
from optimizer.export_power_limit import physical_max_export_kw
from runtime_store.data_model import CURRENT_DATA_MODEL
from runtime_store.migrate_v4 import (
    MigrateV4Error,
    migrate_components_doc,
    migrate_scenarios_doc,
    migrate_plant_ess_to_components,
)


def test_current_data_model_is_4():
    assert CURRENT_DATA_MODEL == 4


def test_normalize_battery_ids_rejects_singular():
    with pytest.raises(ValueError, match="battery_ids"):
        normalize_battery_ids({"battery_id": "a"})


def test_resolve_battery_ids_planning_list():
    batteries = {
        "a": {
            "id": "a",
            "label": "A",
            "kind": "battery_inverter",
            "battery_capacity_kwh": 5.0,
            "battery_max_charge_power_kw": 2.5,
            "battery_max_discharge_power_kw": 2.5,
            "battery_max_power_kw": 2.5,
            "battery_efficiency": 0.97,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "threshold_power": 0.02,
            "standby_power_kw": 0.05,
            "control": "full",
            "limits_from_live": False,
            "ehal_bindings": {},
            "battery_wear": None,
        },
        "b": {
            "id": "b",
            "label": "B",
            "kind": "isolated",
            "battery_capacity_kwh": 10.0,
            "battery_max_charge_power_kw": 5.0,
            "battery_max_discharge_power_kw": 5.0,
            "battery_max_power_kw": 5.0,
            "battery_efficiency": 0.97,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "threshold_power": 0.02,
            "standby_power_kw": 0.1,
            "control": "full",
            "limits_from_live": False,
            "ehal_bindings": {},
            "battery_wear": None,
        },
    }
    resolved = resolve_battery_into_settings({"battery_ids": ["a", "b"]}, batteries)
    assert len(resolved["_planning_batteries"]) == 2
    assert resolved["standby_power_kw"] == pytest.approx(0.15)
    assert resolved["_battery_max_discharge_power_kw_sum"] == pytest.approx(7.5)


def test_ess_field_pattern_b():
    assert ess_field("default_5kwh", "sens_ess_soc") == "ess.default_5kwh.sens_ess_soc"
    expanded = expand_ess_bindings({"sens_ess_soc": "Earnie_Batterie_SoC"}, "default_5kwh")
    assert expanded["ess.default_5kwh.sens_ess_soc"] == "Earnie_Batterie_SoC"


def test_isolated_never_automatik():
    assert not allows_automatik(BATTERY_KIND_ISOLATED)
    milp_plan = {
        "p_grid_buy": 0.0,
        "p_grid_sell": 0.0,
        "p_charge": 0.0,
        "p_discharge": 0.0,
    }
    params = {
        "id": "iso",
        "kind": "isolated",
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "max_charge_power_kw": 2.5,
        "max_discharge_power_kw": 2.5,
        "efficiency": 0.97,
        "standby_power_kw": 0.0,
        "control": "full",
    }
    mode, power, _soc = derive_control_from_milp_plan(
        milp_plan,
        {"expected_p_pv": 0.0, "expected_p_act": 0.0},
        0.0,
        50.0,
        50.0,
        params,
        dt_h=1.0,
    )
    assert mode != MODE_AUTOMATIK
    assert mode == MODE_ENTLADESPERRE
    assert power == 0.0


def test_migrate_scenarios_battery_id_to_ids():
    doc = {
        "earnie_data_model": 3,
        "scenarios": [
            {"id": "live", "label": "Live", "settings": {"battery_id": "default_5kwh"}},
        ],
    }
    out = migrate_scenarios_doc(doc)
    assert out["earnie_data_model"] == 4
    assert out["scenarios"][0]["settings"]["battery_ids"] == ["default_5kwh"]
    assert "battery_id" not in out["scenarios"][0]["settings"]


def test_migrate_components_kind_default():
    doc = {
        "earnie_data_model": 3,
        "batteries": [
            {
                "id": "a",
                "battery_capacity_kwh": 5,
                "battery_max_charge_power_kw": 2.5,
                "battery_max_discharge_power_kw": 2.5,
                "battery_efficiency": 0.97,
                "battery_min_soc": 10,
                "battery_max_soc": 100,
            }
        ],
        "pv_systems": [],
    }
    out = migrate_components_doc(doc)
    assert out["earnie_data_model"] == 4
    assert out["batteries"][0]["kind"] == "battery_inverter"


def test_migrate_plant_ess_ambiguous_raises():
    house = {
        "earnie_data_model": 3,
        "profiles": [
            {
                "id": "live",
                "plant": {
                    "ehal_bindings": {"sens_ess_soc": "Earnie_Batterie_SoC"},
                },
            }
        ],
    }
    components = {
        "earnie_data_model": 3,
        "batteries": [
            {"id": "a", "battery_capacity_kwh": 5},
            {"id": "b", "battery_capacity_kwh": 10},
        ],
    }
    with pytest.raises(MigrateV4Error, match="cannot choose"):
        migrate_plant_ess_to_components(house, components)


def test_physical_max_export_sums_discharge():
    assert physical_max_export_kw(10.0, 2.5 + 5.0) == pytest.approx(17.5)


def test_milp_two_battery_balance_builds():
    from optimizer.milp_horizon import _build_milp_model, coerce_battery_params_list

    batteries = [
        {
            "id": "a",
            "battery_capacity_kwh": 5.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "max_charge_power_kw": 2.5,
            "max_discharge_power_kw": 2.5,
            "max_power_kw": 2.5,
            "efficiency": 0.97,
            "standby_power_kw": 0.0,
            "control": "full",
        },
        {
            "id": "b",
            "battery_capacity_kwh": 10.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "max_charge_power_kw": 5.0,
            "max_discharge_power_kw": 5.0,
            "max_power_kw": 5.0,
            "efficiency": 0.97,
            "standby_power_kw": 0.0,
            "control": "full",
        },
    ]
    assert len(coerce_battery_params_list(batteries)) == 2
    matrix = [
        {
            "expected_p_pv": 3.0,
            "expected_p_act": 1.0,
            "k_act": 20.0,
            "k_push_act": 5.0,
        }
    ]
    model = _build_milp_model(
        matrix,
        1,
        batteries,
        50.0,
        [],
        0.0,
        {},
        {},
    )
    assert model.ess_ids == ["a", "b"]
    assert "a" in model.p_charge_by_ess
    assert "b" in model.e_batt_by_ess
