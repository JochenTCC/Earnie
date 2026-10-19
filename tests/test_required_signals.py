"""Binding P5a — required-signal kinds and activation."""
from __future__ import annotations

from ehal.ess_fields import ess_field
from ehal.inverter_fields import inv_field
from ehal.pv_fields import pv_field
from ehal.required_signals import (
    activate_required_keys,
    missing_required_keys,
    required_binding_keys,
    required_kinds_for_battery,
    required_kinds_for_inverter,
    required_kinds_for_pv_system,
)
from house_config.required_signal_activation import (
    activate_battery_required,
    activate_inverter_required,
    activate_plant_required,
    activate_pv_system_required,
    activate_required_in_components,
    pack_missing_required,
)
from runtime_store.migration.steps.required_signal_activation import (
    STEP_ID,
    apply,
    detect,
)


def test_battery_control_levels():
    assert required_kinds_for_battery("read_only") == ("sens_ess_soc",)
    assert "set_ess_charge_power_limit" in required_kinds_for_battery("limits_only")
    assert "set_ess_active_power" not in required_kinds_for_battery("limits_only")
    assert "set_ess_active_power" in required_kinds_for_battery("full")


def test_battery_keys_entity_scoped():
    keys = required_binding_keys(
        component_kind="battery", entity_id="house", control="full"
    )
    assert ess_field("house", "sens_ess_soc") in keys
    assert ess_field("house", "set_ess_active_power") in keys


def test_activate_preserves_existing_values():
    bindings = {ess_field("house", "sens_ess_soc"): "Merker_SoC"}
    keys = required_binding_keys(
        component_kind="battery", entity_id="house", control="read_only"
    )
    out = activate_required_keys(bindings, keys)
    assert out[ess_field("house", "sens_ess_soc")] == "Merker_SoC"


def test_activate_battery_required_adds_empty_keys():
    bat = activate_battery_required({"id": "house", "control": "full"})
    assert bat["ehal_bindings"][ess_field("house", "sens_ess_soc")] == ""
    assert bat["ehal_bindings"][ess_field("house", "set_ess_active_power")] == ""


def test_activate_plant_required_no_plant_pv():
    plant = activate_plant_required(
        {"ehal_bindings": {"sens_pv_production_active": "Old_PV"}}
    )
    assert plant["ehal_bindings"]["sens_grid_power_active"] == ""
    assert "sens_pv_production_active" not in plant["ehal_bindings"]


def test_pv_system_has_no_required_kinds():
    assert required_kinds_for_pv_system() == ()
    keys = required_binding_keys(component_kind="pv_system", entity_id="dach")
    assert keys == ()


def test_inverter_requires_pv_when_attached():
    assert "sens_inv_power_pv" in required_kinds_for_inverter(
        "read_only", has_attached_pv=True
    )
    assert "sens_inv_power_pv" not in required_kinds_for_inverter(
        "read_only", has_attached_pv=False
    )
    with_pv = activate_inverter_required(
        {"id": "wr", "control": "read_only"},
        pv_systems=[{"id": "p1", "inverter_id": "wr"}],
    )
    assert inv_field("wr", "sens_inv_power_pv") in with_pv["ehal_bindings"]
    without = activate_inverter_required(
        {"id": "wr", "control": "read_only"},
        pv_systems=[],
    )
    assert inv_field("wr", "sens_inv_power_pv") not in without.get("ehal_bindings", {})


def test_strip_empty_pv_production_on_activate():
    key = pv_field("dach", "sens_pv_production_active")
    pv = activate_pv_system_required(
        {"id": "dach", "ehal_bindings": {key: "", "other": "x"}}
    )
    assert key not in pv["ehal_bindings"]
    assert pv["ehal_bindings"]["other"] == "x"
    kept = activate_pv_system_required(
        {"id": "dach", "ehal_bindings": {key: "Merker_PV"}}
    )
    assert kept["ehal_bindings"][key] == "Merker_PV"


def test_pack_missing_inv_pv_when_attached():
    house = {"plant": {"ehal_bindings": {"sens_grid_power_active": ""}}, "profiles": {}}
    components = {
        "batteries": [],
        "inverters": [{"id": "wr", "control": "read_only", "ehal_bindings": {}}],
        "pv_systems": [{"id": "p1", "inverter_id": "wr", "ehal_bindings": {}}],
    }
    assert pack_missing_required(house, components) is True
    updated = activate_required_in_components(components)
    assert inv_field("wr", "sens_inv_power_pv") in updated["inverters"][0]["ehal_bindings"]
    assert pack_missing_required(house, updated) is False


def test_pack_missing_and_migration_step():
    house = {"plant": {"ehal_bindings": {}}, "profiles": {}}
    components = {
        "batteries": [{"id": "house", "control": "read_only", "ehal_bindings": {}}]
    }
    assert pack_missing_required(house, components) is True
    assert detect(
        {"house_profiles.json": house, "components.json": components}
    ) is True
    result = apply(
        {"house_profiles.json": house, "components.json": components},
        {},
    )
    assert STEP_ID.startswith("dm4.")
    assert "house_profiles.json" in result.changed_files
    assert not missing_required_keys(
        result.docs["components.json"]["batteries"][0]["ehal_bindings"],
        required_binding_keys(
            component_kind="battery", entity_id="house", control="read_only"
        ),
    )
    assert pack_missing_required(
        result.docs["house_profiles.json"],
        result.docs["components.json"],
    ) is False
